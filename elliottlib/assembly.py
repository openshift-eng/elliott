import copy
from enum import Enum
import typing

from elliottlib.model import ListModel, Missing, Model


class AssemblyTypes(Enum):
    STREAM = "stream"  # Default assembly type - indicates continuous build and no basis event
    STANDARD = "standard"  # All constraints / checks enforced (e.g. consistent RPMs / siblings)
    CANDIDATE = "candidate"  # Indicates release candidate or feature candidate
    CUSTOM = "custom"  # No constraints enforced
    PREVIEW = "preview"  # Indcates a .next (internal name) or preview release


def assembly_type(releases_config: Model, assembly: typing.Optional[str]) -> AssemblyTypes:
    # If the assembly is not defined in releases.yml, it defaults to stream
    if not assembly or not isinstance(releases_config, Model):
        return AssemblyTypes.STREAM
    target_assembly = releases_config.releases[assembly].assembly
    if not target_assembly:
        return AssemblyTypes.STREAM

    str_type = _assembly_config_struct(releases_config, assembly, 'type', 'standard')
    for assem_type in AssemblyTypes:
        if str_type == assem_type.value:
            return assem_type

    raise ValueError(f'Unknown assembly type: {str_type}')


def _assembly_config_struct(releases_config: Model, assembly: typing.Optional[str], key: str, default):
    """
    If a key is directly under the 'assembly' (e.g. rhcos), then this method will
    recurse the inheritance tree to build you a final version of that key's value.
    The key may refer to a list or dict (set default value appropriately).
    """
    if not assembly or not isinstance(releases_config, Model):
        return Missing

    _check_recursion(releases_config, assembly)
    target_assembly = releases_config.releases[assembly].assembly

    if target_assembly.basis.assembly:  # Does this assembly inherit from another?
        # Recursive apply ancestor assemblies
        parent_config_struct = _assembly_config_struct(releases_config, target_assembly.basis.assembly, key, default)
        if key in target_assembly:
            key_struct = target_assembly[key]
            if hasattr(key_struct, "primitive"):
                key_struct = key_struct.primitive()
            key_struct = merger(key_struct, parent_config_struct.primitive() if hasattr(parent_config_struct, "primitive") else parent_config_struct)
        else:
            key_struct = parent_config_struct
    else:
        key_struct = target_assembly.get(key, default)
    if isinstance(default, dict):
        return Model(dict_to_model=key_struct)
    elif isinstance(default, list):
        return ListModel(list_to_model=key_struct)
    elif isinstance(default, (bool, int, float, str, bytes, type(None))):
        return key_struct
    else:
        raise ValueError(f'Unknown how to derive for default type: {type(default)}')


def merger(a, b):
    """
    Merges two, potentially deep, objects into a new one and returns the result.
    Conceptually, 'a' is layered over 'b' and is dominant when
    necessary. The output is 'c'.
    1. if 'a' specifies a primitive value, regardless of depth, 'c' will contain that value.
    2. if a key in 'a' specifies a list and 'b' has the same key/list, a's list will be appended to b's for c's list.
       Duplicates entries will be removed and primitive (str, int, ..) lists will be returned in sorted order).
    3. if a key ending with '!' in 'a' specifies a value, c's key-! will be to set that value exactly.
    4. if a key ending with a '?' in 'a' specifies a value, c's key-? will be set to that value is 'c' does not contain the key.
    """

    if type(a) in [bool, int, float, str, bytes, type(None)]:
        return a

    c = copy.deepcopy(b)

    if type(a) is list:
        if type(c) is not list:
            return a
        for entry in a:
            if entry not in c:  # do not include duplicates
                c.append(entry)

        if c and type(c[0]) in [str, int, float]:
            return sorted(c)
        return c

    if type(a) is dict:
        if type(c) is not dict:
            return a
        for k, v in a.items():
            if k.endswith('!'):  # full dominant key
                k = k[:-1]
                c[k] = v
            elif k.endswith('?'):  # default value key
                k = k[:-1]
                if k not in c:
                    c[k] = v
            else:
                if k in c:
                    c[k] = merger(a[k], c[k])
                else:
                    c[k] = a[k]
        return c

    raise TypeError(f'Unexpected value type: {type(a)}: {a}')


def _check_recursion(releases_config: Model, assembly: str):
    found = []
    next_assembly = assembly
    while next_assembly and isinstance(releases_config, Model):
        if next_assembly in found:
            raise ValueError(f'Infinite recursion in {assembly} detected; {next_assembly} detected twice in chain')
        found.append(next_assembly)
        target_assembly = releases_config.releases[next_assembly].assembly
        next_assembly = target_assembly.basis.assembly


def assembly_group_config(releases_config: Model, assembly: str, group_config: Model) -> Model:
    """
    Returns a group config based on the assembly information
    and the input group config.
    :param releases_config: A Model for releases.yaml.
    :param assembly: The name of the assembly
    :param group_config: The group config to merge into a new group config (original Model will not be altered)
    :param _visited: Keeps track of visited assembly definitions to prevent infinite recursion.
    """
    if not assembly or not isinstance(releases_config, Model):
        return group_config

    _check_recursion(releases_config, assembly)
    target_assembly = releases_config.releases[assembly].assembly

    if target_assembly.basis.assembly:  # Does this assembly inherit from another?
        # Recursively apply ancestor assemblies
        group_config = assembly_group_config(releases_config, target_assembly.basis.assembly, group_config)

    target_assembly_group = target_assembly.group
    if not target_assembly_group:
        return group_config
    return Model(dict_to_model=merger(target_assembly_group.primitive(), group_config.primitive()))


def assembly_metadata_config(releases_config: Model, assembly: str, meta_type: str, distgit_key: str, meta_config: Model) -> Model:
    """
    Returns a group member's metadata configuration based on the assembly information
    and the initial file-based config.
    :param releases_config: A Model for releases.yaml.
    :param assembly: The name of the assembly
    :param meta_type: 'rpm' or 'image'
    :param distgit_key: The member's distgit_key
    :param meta_config: The meta's config object
    :return: Returns a computed config for the metadata (e.g. value for meta.config).
    """
    if not assembly or not isinstance(releases_config, Model):
        return meta_config

    _check_recursion(releases_config, assembly)
    target_assembly = releases_config.releases[assembly].assembly

    if target_assembly.basis.assembly:  # Does this assembly inherit from another?
        # Recursive apply ancestor assemblies
        meta_config = assembly_metadata_config(releases_config, target_assembly.basis.assembly, meta_type, distgit_key, meta_config)

    config_dict = meta_config.primitive()

    component_list = target_assembly.members[f'{meta_type}s']
    for component_entry in component_list:
        if component_entry.distgit_key == '*' or component_entry.distgit_key == distgit_key and component_entry.metadata:
            config_dict = merger(component_entry.metadata.primitive(), config_dict)

    return Model(dict_to_model=config_dict)


def assembly_rhcos_config(releases_config: Model, assembly: str) -> Model:
    """
    :param releases_config: The content of releases.yml in Model form.
    :param assembly: The name of the assembly to assess
    Returns the a computed rhcos config model for a given assembly.
    """
    return _assembly_field("rhcos", releases_config, assembly)


def assembly_issues_config(releases_config: Model, assembly: str) -> Model:
    """
    :param releases_config: The content of releases.yml in Model form.
    :param assembly: The name of the assembly to assess
    Returns the a computed issues config model for a given assembly.
    """
    return _assembly_field("issues", releases_config, assembly)


def _assembly_field(field_name: str, releases_config: Model, assembly: str) -> Model:
    """
    :param field_name: the field name
    :param releases_config: The content of releases.yml in Model form.
    :param assembly: The name of the assembly to assess
    Returns the a computed rhcos config model for a given assembly.
    """
    if not assembly or not isinstance(releases_config, Model):
        return Missing

    _check_recursion(releases_config, assembly)
    target_assembly = releases_config.releases[assembly].assembly
    config_dict = target_assembly.get(field_name, {})
    if target_assembly.basis.assembly:  # Does this assembly inherit from another?
        # Recursive apply ancestor assemblies
        basis_rhcos_config = _assembly_field(field_name, releases_config, target_assembly.basis.assembly)
        config_dict = merger(config_dict, basis_rhcos_config.primitive())
    return Model(dict_to_model=config_dict)


def assembly_basis_event(releases_config: Model, assembly: str, strict: bool = False) -> typing.Optional[int]:
    """
    :param releases_config: The content of releases.yml in Model form.
    :param assembly: The name of the assembly to assess
    :param strict: Raise exception if assembly not found
    Returns the basis event for a given assembly. If the assembly has no basis event,
    None is returned.
    """
    if not assembly or not isinstance(releases_config, Model):
        if strict:
            raise ValueError("given assembly not found in releases config")
        return None

    _check_recursion(releases_config, assembly)
    target_assembly = releases_config.releases[assembly].assembly
    if target_assembly.basis.brew_event:
        return int(target_assembly.basis.brew_event)
    return assembly_basis_event(releases_config, target_assembly.basis.assembly, strict=strict)


def assembly_config_finalize(releases_config: Model, assembly: str, rpm_metas, ordered_image_metas):
    """
    Some metadata cannot be finalized until all metadata is read in by doozer. This method
    uses that interpreted metadata set to go through and adjust assembly information
    within it.
    :param releases_config: The releases.yml Model
    :param assembly: The name of the assembly to apply
    :param rpm_metas: A list of rpm metadata to update relative to the assembly.
    :param ordered_image_metas: A list of image metadata to update relative to the assembly.
    :return: N/A. Metas are updated in-place. Only call during runtime.initialize.
    """
    _check_recursion(releases_config, assembly)
    pass
