import numpy as np
import json

from ..constants import log
from .. import util

from .stl import export_stl, export_stl_ascii
from .urdf import export_urdf
from .ply import _ply_exporters


def export_mesh(mesh, file_obj, file_type=None):
    '''
    Export a Trimesh object to a file- like object, or to a filename

    Parameters
    ---------
    file_obj: a filename string or a file-like object
    file_type: str representing file type (eg: 'stl')
    process:   boolean flag, whether to process the mesh on load

    Returns:
    mesh: a single Trimesh object, or a list of Trimesh objects,
          depending on the file format.

    '''
    # if we opened a file object in this function
    # we will want to close it when we're done
    was_opened = False

    if util.is_string(file_obj):
        if file_type is None:
            file_type = (str(file_obj).split('.')[-1]).lower()
        if file_type in _mesh_exporters:
            was_opened = True
            file_obj = open(file_obj, 'wb')
    file_type = str(file_type).lower()

    if not (file_type in _mesh_exporters):
        raise ValueError('%s exporter not available!', file_type)

    log.debug('Exporting %d faces as %s', len(mesh.faces), file_type.upper())
    export = _mesh_exporters[file_type](mesh)

    if hasattr(file_obj, 'write'):
        result = util.write_encoded(file_obj, export)
    else:
        result = export

    if was_opened:
        file_obj.close()

    return result


def export_off(mesh):
    '''
    Export a mesh as an OFF file, a simple text format

    Parameters
    -----------
    mesh: Trimesh object

    Returns
    -----------
    export: str, string of OFF format output
    '''
    # prepend a 3 (face count) to each face
    faces_stacked = np.column_stack((np.ones(len(mesh.faces)) * 3,
                                     mesh.faces)).astype(np.int64)
    export = 'OFF\n'
    export += str(len(mesh.vertices)) + ' ' + str(len(mesh.faces)) + ' 0\n'
    export += util.array_to_string(mesh.vertices,
                                   col_delim=' ',
                                   row_delim='\n',
                                   digits=8) + '\n'
    export += util.array_to_string(faces_stacked,
                                   col_delim=' ',
                                   row_delim='\n')
    return export


def export_obj(mesh, include_normals=True, include_texture=True):
    '''
    Export a mesh as a Wavefront OBJ file

    Parameters
    -----------
    mesh: Trimesh object

    Returns
    -----------
    export: str, string of OBJ format output
    '''
    # store the multiple options for formatting a vertex index for a face
    face_formats = {('v',): '{}',
                    ('v', 'vn'): '{}//{}',
                    ('v', 'vt'): '{}/{}',
                    ('v', 'vn', 'vt'): '{}/{}/{}'}
    # we are going to reference face_formats with this
    face_type = ['v']

    export = 'v '
    export += util.array_to_string(mesh.vertices,
                                   col_delim=' ',
                                   row_delim='\nv ',
                                   digits=8) + '\n'

    if include_normals and 'vertex_normals' in mesh._cache:
        # if vertex normals are stored in cache export them
        # these will have been autogenerated if they have ever been called
        face_type.append('vn')
        export += 'vn '
        export += util.array_to_string(mesh.vertex_normals,
                                       col_delim=' ',
                                       row_delim='\nvn ',
                                       digits=8) + '\n'

    if (include_texture and
        'vertex_texture' in mesh.metadata and
            len(mesh.metadata['vertex_texture']) == len(mesh.vertices)):
        # if vertex texture exists and is the right shape export here
        face_type.append('vt')
        export += 'vt '
        export += util.array_to_string(mesh.metadata['vertex_texture'],
                                       col_delim=' ',
                                       row_delim='\nvt ',
                                       digits=8) + '\n'

    # the format for a single vertex reference of a face
    face_format = face_formats[tuple(face_type)]
    # how many times is each index included
    count = face_format.count('{}')
    # shape the output array so we can do a single format operation
    shaped = np.tile(mesh.faces.reshape((-1, 1)) + 1,
                     (1, count)).reshape(-1)

    # create a single large format string
    formatter = '\nf ' + ' '.join(face_format for i in range(3))
    formatter *= len(mesh.faces)
    # truncate the leading newline and run the format operation
    faces = formatter[1:].format(*shaped)

    # add the exported faces to the
    export += faces

    return export


def export_collada(mesh):
    '''
    Export a mesh as a COLLADA file.
    '''
    from ..resources import get_resource

    from string import Template

    template_string = get_resource('collada.dae.template')
    template = Template(template_string)

    # we bother setting this because np.array2string uses these printoptions
    np.set_printoptions(threshold=np.inf, precision=5, linewidth=np.inf)
    replacement = dict()
    replacement['VERTEX'] = np.array2string(mesh.vertices.reshape(-1))[1:-1]
    replacement['FACES'] = np.array2string(mesh.faces.reshape(-1))[1:-1]
    replacement['NORMALS'] = np.array2string(
        mesh.vertex_normals.reshape(-1))[1:-1]
    replacement['VCOUNT'] = str(len(mesh.vertices))
    replacement['VCOUNTX3'] = str(len(mesh.vertices) * 3)
    replacement['FCOUNT'] = str(len(mesh.faces))

    export = template.substitute(replacement)
    return export


def export_dict64(mesh):
    return export_dict(mesh, encoding='base64')


def export_dict(mesh, encoding=None):
    def encode(item, dtype=None):
        if encoding is None:
            return item.tolist()
        else:
            if dtype is None:
                dtype = item.dtype
            return util.array_to_encoded(item,
                                         dtype=dtype,
                                         encoding=encoding)

    export = {'metadata': util.tolist_dict(mesh.metadata),
              'faces': encode(mesh.faces),
              'face_normals': encode(mesh.face_normals),
              'vertices': encode(mesh.vertices)}
    if mesh.visual.kind == 'face':
        export['face_colors'] = encode(mesh.visual.face_colors)
    elif mesh.visual.kind == 'vertex':
        export['vertex_colors'] = encode(mesh.visual.vertex_colors)

    return export


def export_json(mesh):
    blob = export_dict(mesh, encoding='base64')
    export = json.dumps(blob)
    return export


def export_msgpack(mesh):
    import msgpack
    blob = export_dict(mesh, encoding='binary')
    export = msgpack.dumps(blob)
    return export


_mesh_exporters = {'stl': export_stl,
                   'dict': export_dict,
                   'json': export_json,
                   'off': export_off,
                   'obj': export_obj,
                   'dae': export_collada,
                   'dict64': export_dict64,
                   'msgpack': export_msgpack,
                   'collada': export_collada,
                   'stl_ascii': export_stl_ascii}

_mesh_exporters.update(_ply_exporters)
