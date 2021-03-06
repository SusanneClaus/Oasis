__author__ = "Mikael Mortensen <mikaem@math.uio.no>"
__date__ = "2013-06-25"
__copyright__ = "Copyright (C) 2013 " + __author__
__license__  = "GNU Lesser GPL version 3 or any later version"

from problems import *

# Create a mesh here
class Submesh(SubDomain):
    def inside(self, x, on_boundary):
        return x[0] > 0.25 - DOLFIN_EPS and x[1] > 0.25 - DOLFIN_EPS

def mesh(Nx, Ny, **params):
    mesh_ = UnitSquareMesh(Nx, Ny)
    subm = Submesh()
    mf1 = MeshFunction("size_t", mesh_, 2)
    mf1.set_all(0)
    subm.mark(mf1, 1)
    return SubMesh(mesh_, mf1, 0)

# Override some problem specific parameters
Re = 200.
nu = 1./Re
NS_parameters.update(dict(
    nu = nu,
    T = 10,
    dt = 0.01,
    Re = Re,
    Nx = 40,
    Ny = 40,
    folder = "Lshape_results",
    max_iter = 1,
    plot_interval = 1,
    velocity_degree = 2,
    velocity_update_type = "lumping",
    use_krylov_solvers = True
  )
)

def inlet(x, on_boundary):
    return near(x[1] - 1., 0.) and on_boundary

def outlet(x, on_boundary):
    return near(x[0] - 1., 0.) and on_boundary

def walls(x, on_boundary):
    return (near(x[0], 0.) or near(x[1], 0.) or 
            (x[0] > 0.25 - 5*DOLFIN_EPS  and 
             x[1] > 0.25 - 5*DOLFIN_EPS) and on_boundary)

p_in = Expression("sin(pi*t)", t=0.)
def create_bcs(V, Q, sys_comp, **NS_namespace):
    bcs = dict((ui, []) for ui in sys_comp)    
    bc0 = DirichletBC(V, 0., walls)
    pc0 = DirichletBC(Q, p_in, inlet)
    pc1 = DirichletBC(Q, 0.0, outlet)
    bcs['u0'] = [bc0]
    bcs['u1'] = [bc0]
    bcs['p'] = [pc0, pc1]
    return bcs

def pre_solve_hook(mesh, **NS_namespace):
    Vv = VectorFunctionSpace(mesh, 'CG', 1)
    return dict(Vv=Vv, uv=Function(Vv))

def start_timestep_hook(t, **NS_namespace):
    p_in.t = t
    
def temporal_hook(tstep, q_, u_, uv, Vv, plot_interval, **NS_namespace):
    if tstep % plot_interval == 0:
        plot(q_['p'], title="Pressure")
        uv.assign(project(u_, Vv))
        plot(uv, title="Velocity")
