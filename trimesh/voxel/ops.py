import numpy as np

from .. import util
from ..constants import log


def fill_orthographic(dense):
    shape = dense.shape
    indices = np.stack(
        np.meshgrid(*(np.arange(s) for s in shape), indexing='ij'),
        axis=-1)
    empty = np.logical_not(dense)

    def fill_axis(axis):
        base_local_indices = indices[..., axis]
        local_indices = base_local_indices.copy()
        local_indices[empty] = shape[axis]
        mins = np.min(local_indices, axis=axis, keepdims=True)
        local_indices = base_local_indices.copy()
        local_indices[empty] = -1
        maxs = np.max(local_indices, axis=axis, keepdims=True)

        return np.logical_and(
            base_local_indices >= mins,
            base_local_indices <= maxs,
        )

    filled = fill_axis(axis=0)
    for axis in range(1, len(shape)):
        filled = np.logical_and(filled, fill_axis(axis))
    return filled


def fill_base(sparse_indices):
    """
    Given a sparse surface voxelization, fill in between columns.

    Parameters
    --------------
    sparse_indices: (n, 3) int, location of filled cells

    Returns
    --------------
    filled: (m, 3) int, location of filled cells
    """
    # validate inputs
    sparse_indices = np.asanyarray(sparse_indices, dtype=np.int64)
    if not util.is_shape(sparse_indices, (-1, 3)):
        raise ValueError('incorrect shape')

    # create grid and mark inner voxels
    max_value = sparse_indices.max() + 3

    grid = np.zeros((max_value,
                     max_value,
                     max_value),
                    bool)
    voxels_sparse = np.add(sparse_indices, 1)

    grid[tuple(voxels_sparse.T)] = 1

    for i in range(max_value):
        check_dir2 = False
        for j in range(0, max_value - 1):
            idx = []
            # find transitions first
            # transition positions are from 0 to 1 and from 1 to 0
            eq = np.equal(grid[i, j, :-1], grid[i, j, 1:])
            idx = np.where(np.logical_not(eq))[0] + 1
            c = len(idx)
            check_dir2 = (c % 4) > 0 and c > 4
            if c < 4:
                continue
            for s in range(0, c - c % 4, 4):
                grid[i, j, idx[s]:idx[s + 3]] = 1
        if not check_dir2:
            continue

        # check another direction for robustness
        for k in range(0, max_value - 1):
            idx = []
            # find transitions first
            eq = np.equal(grid[i, :-1, k], grid[i, 1:, k])
            idx = np.where(np.logical_not(eq))[0] + 1
            c = len(idx)
            if c < 4:
                continue
            for s in range(0, c - c % 4, 4):
                grid[i, idx[s]:idx[s + 3], k] = 1

    # generate new voxels
    filled = np.column_stack(np.where(grid))
    filled -= 1

    return filled


fill_voxelization = fill_base


def matrix_to_marching_cubes(matrix, pitch=1.0):
    """
    Convert an (n,m,p) matrix into a mesh, using marching_cubes.

    Parameters
    -----------
    matrix : (n, m, p) bool
      Occupancy array

    Returns
    ----------
    mesh : trimesh.Trimesh
      Mesh generated by meshing voxels using
      the marching cubes algorithm in skimage
    """
    from skimage import measure
    from ..base import Trimesh

    matrix = np.asanyarray(matrix, dtype=np.bool)

    rev_matrix = np.logical_not(matrix)  # Takes set about 0.
    # Add in padding so marching cubes can function properly with
    # voxels on edge of AABB
    pad_width = 1
    rev_matrix = np.pad(rev_matrix,
                        pad_width=(pad_width),
                        mode='constant',
                        constant_values=(1))

    # pick between old and new API
    if hasattr(measure, 'marching_cubes_lewiner'):
        func = measure.marching_cubes_lewiner
    else:
        func = measure.marching_cubes

    # Run marching cubes.
    pitch = np.asanyarray(pitch)
    if pitch.size == 1:
        pitch = (pitch,) * 3
    meshed = func(volume=rev_matrix,
                  level=.5,  # it is a boolean voxel grid
                  spacing=pitch)

    # allow results from either marching cubes function in skimage
    # binaries available for python 3.3 and 3.4 appear to use the classic
    # method
    if len(meshed) == 2:
        log.warning('using old marching cubes, may not be watertight!')
        vertices, faces = meshed
        normals = None
    elif len(meshed) == 4:
        vertices, faces, normals, vals = meshed

    # Return to the origin, add in the pad_width
    vertices = np.subtract(vertices, pad_width)
    # create the mesh
    mesh = Trimesh(vertices=vertices,
                   faces=faces,
                   vertex_normals=normals)
    return mesh


def sparse_to_matrix(sparse):
    """
    Take a sparse (n,3) list of integer indexes of filled cells,
    turn it into a dense (m,o,p) matrix.

    Parameters
    -----------
    sparse : (n, 3) int
      Index of filled cells

    Returns
    ------------
    dense : (m, o, p) bool
      Matrix of filled cells
    """

    sparse = np.asanyarray(sparse, dtype=np.int)
    if not util.is_shape(sparse, (-1, 3)):
        raise ValueError('sparse must be (n,3)!')

    shape = sparse.max(axis=0) + 1
    matrix = np.zeros(np.product(shape), dtype=np.bool)
    multiplier = np.array([np.product(shape[1:]), shape[2], 1])

    index = (sparse * multiplier).sum(axis=1)
    matrix[index] = True

    dense = matrix.reshape(shape)
    return dense


def points_to_marching_cubes(points, pitch=1.0):
    """
    Mesh points by assuming they fill a voxel box, and then
    running marching cubes on them

    Parameters
    ------------
    points : (n, 3) float
      Points in 3D space

    Returns
    -------------
    mesh : trimesh.Trimesh
      Points meshed using marching cubes
    """
    # make sure inputs are as expected
    points = np.asanyarray(points, dtype=np.float64)
    pitch = np.asanyarray(pitch, dtype=float)

    # find the minimum value of points for origin
    origin = points.min(axis=0)
    # convert points to occupied voxel cells
    index = ((points - origin) / pitch).round().astype(np.int64)

    # convert voxel indices to a matrix
    matrix = sparse_to_matrix(index)

    # run marching cubes on the matrix to generate a mesh
    mesh = matrix_to_marching_cubes(matrix)
    mesh.vertices += origin

    return mesh


def multibox(centers, colors=None):
    """
    Return a Trimesh object with a box at every center.

    Doesn't do anything nice or fancy.

    Parameters
    -----------
    centers: (n,3) float, center of boxes that are occupied
    pitch:   float, the edge length of a voxel
    colors: (3,) or (4,) or (n,3) or (n, 4) float, color of boxes

    Returns
    ---------
    rough: Trimesh object representing inputs
    """
    from .. import primitives
    from ..base import Trimesh

    b = primitives.Box()

    # v = np.expand_dims(centers, axis=0)
    # v = v + np.expand_dims(b.vertices, axis=1)
    # v = v.reshape((-1, 3))

    # vertices_per_box = len(b.vertices)
    # f = np.expand_dims(np.arange(len(centers)) * vertices_per_box, axis=0)
    # f = f + np.expand_dims(np.arange(vertices_per_box), axis=1)
    # f = f.reshape((-1, 3))

    v = np.tile(centers, (1, len(b.vertices))).reshape((-1, 3))
    v += np.tile(b.vertices, (len(centers), 1))

    f = np.tile(b.faces, (len(centers), 1))
    f += np.tile(np.arange(len(centers)) * len(b.vertices),
                 (len(b.faces), 1)).T.reshape((-1, 1))

    face_colors = None
    if colors is not None:
        colors = np.asarray(colors)
        if colors.ndim == 1:
            colors = colors[None].repeat(len(centers), axis=0)
        if colors.ndim == 2 and len(colors) == len(centers):
            face_colors = colors.repeat(12, axis=0)

    mesh = Trimesh(vertices=v,
                   faces=f,
                   face_colors=face_colors)

    return mesh


def boolean_sparse(a, b, operation=np.logical_and):
    """
    Find common rows between two arrays very quickly
    using 3D boolean sparse matrices.

    Parameters
    -----------
    a: (n, d)  int, coordinates in space
    b: (m, d)  int, coordinates in space
    operation: numpy operation function, ie:
                  np.logical_and
                  np.logical_or

    Returns
    -----------
    coords: (q, d) int, coordinates in space
    """
    # 3D sparse arrays, using wrapped scipy.sparse
    # pip install sparse
    import sparse

    # find the bounding box of both arrays
    extrema = np.array([a.min(axis=0),
                        a.max(axis=0),
                        b.min(axis=0),
                        b.max(axis=0)])
    origin = extrema.min(axis=0) - 1
    size = tuple(extrema.ptp(axis=0) + 2)

    # put nearby voxel arrays into same shape sparse array
    sp_a = sparse.COO((a - origin).T,
                      data=np.ones(len(a), dtype=np.bool),
                      shape=size)
    sp_b = sparse.COO((b - origin).T,
                      data=np.ones(len(b), dtype=np.bool),
                      shape=size)

    # apply the logical operation
    # get a sparse matrix out
    applied = operation(sp_a, sp_b)
    # reconstruct the original coordinates
    coords = np.column_stack(applied.coords) + origin

    return coords


def strip_array(data):
    shape = data.shape
    ndims = len(shape)
    padding = []
    slices = []
    for dim, size in enumerate(shape):
        axis = tuple(range(dim)) + tuple(range(dim + 1, ndims))
        filled = np.any(data, axis=axis)
        indices, = np.nonzero(filled)
        pad_left = indices[0]
        pad_right = indices[-1]
        padding.append([pad_left, pad_right])
        slices.append(slice(pad_left, pad_right))
    return data[tuple(slices)], np.array(padding, int)


def indices_to_points(indices, pitch=None, origin=None):
    """
    Convert indices of an (n,m,p) matrix into a set of voxel center points.

    Parameters
    ----------
    indices: (q, 3) int, index of voxel matrix (n,m,p)
    pitch: float, what pitch was the voxel matrix computed with
    origin: (3,) float, what is the origin of the voxel matrix

    Returns
    ----------
    points: (q, 3) float, list of points
    """
    indices = np.asanyarray(indices)
    if indices.shape[1:] != (3,):
        from IPython import embed
        embed()
        raise ValueError('shape of indices must be (q, 3)')

    points = np.array(indices, dtype=np.float64)
    if pitch is not None:
        points *= float(pitch)
    if origin is not None:
        origin = np.asanyarray(origin)
        if origin.shape != (3,):
            raise ValueError('shape of origin must be (3,)')
        points += origin

    return points


def matrix_to_points(matrix, pitch=None, origin=None):
    """
    Convert an (n,m,p) matrix into a set of points for each voxel center.

    Parameters
    -----------
    matrix: (n,m,p) bool, voxel matrix
    pitch: float, what pitch was the voxel matrix computed with
    origin: (3,) float, what is the origin of the voxel matrix

    Returns
    ----------
    points: (q, 3) list of points
    """
    indices = np.column_stack(np.nonzero(matrix))
    points = indices_to_points(indices=indices,
                               pitch=pitch,
                               origin=origin)
    return points


def points_to_indices(points, pitch=None, origin=None):
    """
    Convert center points of an (n,m,p) matrix into its indices.

    Parameters
    ----------
    points : (q, 3) float
      Center points of voxel matrix (n,m,p)
    pitch : float
      What pitch was the voxel matrix computed with
    origin : (3,) float
      What is the origin of the voxel matrix

    Returns
    ----------
    indices : (q, 3) int
      List of indices
    """
    points = np.array(points, dtype=np.float64)
    if points.shape != (points.shape[0], 3):
        raise ValueError('shape of points must be (q, 3)')

    if origin is not None:
        origin = np.asanyarray(origin)
        if origin.shape != (3,):
            raise ValueError('shape of origin must be (3,)')
        points -= origin
    if pitch is not None:
        points /= pitch

    origin = np.asanyarray(origin, dtype=np.float64)
    pitch = float(pitch)

    indices = np.round(points).astype(int)
    return indices
