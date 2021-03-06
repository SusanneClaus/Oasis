__author__ = "Mikael Mortensen <mikaem@math.uio.no>"
__date__ = "2013-06-25"
__copyright__ = "Copyright (C) 2013 " + __author__
__license__  = "GNU Lesser GPL version 3 or any later version"

from dolfin import *
from commands import getoutput
from os import getpid, path
from collections import defaultdict
from numpy import array, maximum, zeros

try:
    from fenicstools import getMemoryUsage

except:    
    def getMemoryUsage(rss=True):
        mypid = getpid()
        if rss:
            mymemory = getoutput("ps -o rss %s" % mypid).split()[1]
        else:
            mymemory = getoutput("ps -o vsz %s" % mypid).split()[1]
        return eval(mymemory)

parameters["linear_algebra_backend"] = "PETSc"
parameters["form_compiler"]["optimize"] = True
parameters["form_compiler"]["cpp_optimize"] = True
parameters["form_compiler"]["representation"] = "quadrature"
#parameters["form_compiler"]["cache_dir"] = "instant"
parameters["form_compiler"]["cpp_optimize_flags"] = "-O3 --fast-math"
parameters["mesh_partitioner"] = "ParMETIS"
parameters["form_compiler"].add("no_ferari", True)
#set_log_active(False)

# Default parameters
NS_parameters = dict(
  # Physical constants and solver parameters
  nu = 0.01,             # Kinematic viscosity
  t = 0.0,               # Time
  tstep = 0,             # Timestep
  T = 1.0,               # End time
  dt = 0.01,             # Time interval on each timestep
  
  # Some discretization options
  AB_projection_pressure = False,  # Use Adams Bashforth projection as first estimate for pressure on new timestep
  velocity_degree = 2,
  pressure_degree = 1,  
  solver = "IPCS_ABCN",  # "IPCS_ABCN", "IPCS_ABE", "IPCS", "Chorin"
  
  # Parameters used to tweek solver  
  max_iter = 1,          # Number of inner pressure velocity iterations on timestep
  max_error = 1e-6,      # Tolerance for inner iterations (pressure velocity iterations)
  iters_on_first_timestep = 2,  # Number of iterations on first timestep
  use_krylov_solvers = False,  # Otherwise use LU-solver
  low_memory_version = False,  # Use assembler and not preassembled matrices
  print_intermediate_info = 10,
  print_velocity_pressure_convergence = False,
  velocity_update_type = "default",
  
  # Parameters used to tweek output  
  plot_interval = 10,    
  checkpoint = 10,       # Overwrite solution in Checkpoint folder each checkpoint tstep
  save_step = 10,        # Store solution in new folder each save_step tstep
  folder = 'results',    # Relative folder for storing results 
  restart_folder = None, # If restarting solution, set the folder holding the solution to start from here
  output_timeseries_as_vector = True, # Store velocity as vector in Timeseries 
  
  # Solver parameters that will be transferred to dolfins parameters['krylov_solver']
  krylov_solvers = dict(
    monitor_convergence = False,
    report = False,
    error_on_nonconvergence = False,
    nonzero_initial_guess = True,
    maximum_iterations = 200,
    relative_tolerance = 1e-8,
    absolute_tolerance = 1e-8)
)

constrained_domain = None

# To solve for scalars provide a list like ['scalar1', 'scalar2']
scalar_components = []

# With diffusivities given as a Schmidt number defined by:
#   Schmidt = nu / D (= momentum diffusivity / mass diffusivity)
Schmidt = defaultdict(lambda: 1.)

# The following helper functions are available in dolfin
# They are redefined here for printing only on process 0. 
RED   = "\033[1;37;31m%s\033[0m"
BLUE  = "\033[1;37;34m%s\033[0m"
GREEN = "\033[1;37;32m%s\033[0m"

def info_blue(s, check=True):
    if MPI.rank(mpi_comm_world())==0 and check:
        print BLUE % s

def info_green(s, check=True):
    if MPI.rank(mpi_comm_world())==0 and check:
        print GREEN % s
    
def info_red(s, check=True):
    if MPI.rank(mpi_comm_world())==0 and check:
        print RED % s

class OasisTimer(Timer):
    def __init__(self, task, verbose=False):
        Timer.__init__(self, task)
        info_blue(task, verbose)
        
class OasisMemoryUsage:
    def __init__(self, s):
        self.memory = 0
        self.memory_vm = 0
        self(s)
        
    def __call__(self, s, verbose=False):
        self.prev = self.memory
        self.prev_vm = self.memory_vm
        self.memory = MPI.sum(mpi_comm_world(), getMemoryUsage())
        self.memory_vm = MPI.sum(mpi_comm_world(), getMemoryUsage(False))
        if MPI.rank(mpi_comm_world()) == 0 and verbose:
            info_blue('{0:26s}  {1:10d} MB {2:10d} MB {3:10d} MB {4:10d} MB'.format(s, 
                   self.memory-self.prev, self.memory, self.memory_vm-self.prev_vm, self.memory_vm))

# Print memory use up til now
initial_memory_use = getMemoryUsage()
oasis_memory = OasisMemoryUsage('Start')

# Convenience functions
def strain(u):
    return 0.5*(grad(u)+ grad(u).T)

def omega(u):
    return 0.5*(grad(u) - grad(u).T)

def Omega(u):
    return inner(omega(u), omega(u))

def Strain(u):
    return inner(strain(u), strain(u))

def QC(u):
    return Omega(u) - Strain(u)

def recursive_update(dst, src):
    """Update dict dst with items from src deeply ("deep update")."""
    for key, val in src.items():
        if key in dst and isinstance(val, dict) and isinstance(dst[key], dict):
            dst[key] = recursive_update(dst[key], val)
        else:
            dst[key] = val
    return dst

def add_function_to_tstepfiles(function, newfolder, tstepfiles, tstep):
    name = function.name()
    tstepfolder = path.join(newfolder, "Timeseries")
    tstepfiles[name] = XDMFFile(mpi_comm_world(), 
                                path.join(tstepfolder, 
                                '{}_from_tstep_{}.xdmf'.format(name, tstep)))
    tstepfiles[name].function = function
    tstepfiles[name].parameters["rewrite_function_mesh"] = False

def body_force(mesh, **NS_namespace):
    """Specify body force"""
    return Constant((0,)*mesh.geometry().dim())

def scalar_source(scalar_components, **NS_namespace):
    """Return a dictionary of scalar sources."""
    return dict((ci, Constant(0)) for ci in scalar_components)
    
def initialize(**NS_namespace):
    """Initialize solution."""
    pass

def create_bcs(sys_comp, **NS_namespace):
    """Return dictionary of Dirichlet boundary conditions."""
    return dict((ui, []) for ui in sys_comp)

def velocity_tentative_hook(**NS_namespace):
    """Called just prior to solving for tentative velocity."""
    pass

def pressure_hook(**NS_namespace):
    """Called prior to pressure solve."""
    pass

def scalar_hook(**NS_namespace):
    """Called prior to scalar solve."""
    pass

def start_timestep_hook(**NS_namespace):
    """Called at start of new timestep"""
    pass

def temporal_hook(**NS_namespace):
    """Called at end of a timestep."""
    pass

def pre_solve_hook(**NS_namespace):
    """Called just prior to entering time-loop. Must return a dictionary."""
    return {}

def theend_hook(**NS_namespace):
    """Called at the very end."""
    pass
