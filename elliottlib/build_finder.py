from elliottlib.imagecfg import ImageMetadata
import logging
from logging import Logger
from typing import Dict, Iterable, List, Optional, Union

from koji import ClientSession

from elliottlib.assembly import assembly_metadata_config, assembly_rhcos_config
from elliottlib.brew import get_build_objects
from elliottlib.model import Model
from elliottlib.rpmcfg import RPMMetadata
from elliottlib.util import find_latest_builds, parse_nvr, strip_epoch, to_nvre


class BuildFinder:
    """ A helper class for finding builds.
    """
    def __init__(self, koji_api: ClientSession, logger: Optional[Logger] = None) -> None:
        self._koji_api = koji_api
        self._logger = logger or logging.getLogger(__name__)
        self._build_cache: Dict[str, Optional[Dict]] = {}  # Cache build_id/nvre -> build_dict to prevent unnecessary queries.

    def _get_builds(self, ids_or_nvrs: Iterable[Union[int, str]]) -> List[Dict]:
        """ Get build dicts from Brew. This method uses an internal cache to avoid unnecessary queries.
        :params ids_or_nvrs: list of build IDs or NVRs
        :return: a list of Brew build dicts
        """
        cache_miss = set(ids_or_nvrs) - self._build_cache.keys()
        if cache_miss:
            cache_miss = [strip_epoch(item) if isinstance(item, str) else item for item in cache_miss]
            builds = get_build_objects(cache_miss, self._koji_api)
            for id_or_nvre, build in zip(cache_miss, builds):
                if build:
                    self._cache_build(build)
                else:
                    self._build_cache[id_or_nvre] = None  # None indicates the build ID or NVRE doesn't exist
        return [self._build_cache[id] for id in ids_or_nvrs]

    def _cache_build(self, build: Dict):
        """ Save build dict to cache """
        self._build_cache[build["build_id"]] = build
        self._build_cache[build["nvr"]] = build
        if "epoch" in build:
            self._build_cache[to_nvre(build)] = build

    def from_tag(self, build_type: str, tag: str, inherit: bool, assembly: Optional[str], event: Optional[int] = None) -> Dict[str, Dict]:
        """ Returns builds from the specified brew tag
        :param build_type: "rpm" or "image"
        :param tag: Brew tag name
        :param inherit: Descend into brew tag inheritance
        :param assembly: Assembly name to query. If None, this method will return true latest builds.
        :param event: Brew event ID
        :return: a dict; keys are component names, values are Brew build dicts
        """
        if not assembly:
            # Assemblies are disabled. We need the true latest tagged builds in the brew tag
            self._logger.info("Finding latest builds in Brew tag %s...", tag)
            builds = self._koji_api.listTagged(tag, latest=True, inherit=inherit, event=event, type=build_type)
        else:
            # Assemblies are enabled. We need all tagged builds in the brew tag then find the latest ones for the assembly.
            self._logger.info("Finding builds specific to assembly %s in Brew tag %s...", assembly, tag)
            tagged_builds = self._koji_api.listTagged(tag, latest=False, inherit=inherit, event=event, type=build_type)
            builds = find_latest_builds(tagged_builds, assembly)
        component_builds = {build["name"]: build for build in builds}
        self._logger.info("Found %s builds.", len(component_builds))
        for build in component_builds.values():  # Save to cache
            self._cache_build(build)
        return component_builds

    def from_pinned_by_is(self, el_version: int, assembly: str, releases_config: Model, rpm_map: Dict[str, RPMMetadata]) -> Dict[str, Dict]:
        """ Returns RPM builds pinned by "is" in assembly config
        :param el_version: RHEL version
        :param assembly: Assembly name to query. If None, this method will return true latest builds.
        :param releases_config: a Model for releases.yaml
        :param rpm_map: Map of rpm_distgit_key -> RPMMetadata
        :return: a dict; keys are component names, values are Brew build dicts
        """
        pinned_nvrs: Dict[str, str] = {}  # rpms pinned to the runtime assembly; keys are rpm component names, values are nvrs
        component_builds: Dict[str, Dict] = {}  # rpms pinned to the runtime assembly; keys are rpm component names, values are brew build dicts

        # Honor pinned rpm nvrs pinned by "is"
        for distgit_key, rpm_meta in rpm_map.items():
            meta_config = assembly_metadata_config(releases_config, assembly, 'rpm', distgit_key, rpm_meta.config)
            nvr = meta_config["is"][f"el{el_version}"]
            if not nvr:
                continue
            nvre_obj = parse_nvr(str(nvr))
            if nvre_obj["name"] != rpm_meta.rpm_name:
                raise ValueError(f"RPM {nvr} is pinned to assembly {assembly} for distgit key {distgit_key}, but its package name is not {rpm_meta.rpm_name}.")
            pinned_nvrs[nvre_obj["name"]] = nvr
        if pinned_nvrs:
            pinned_nvr_list = list(pinned_nvrs.values())
            self._logger.info("Found %s NVRs pinned to the runtime assembly %s. Fetching build infos from Brew...", len(pinned_nvr_list), assembly)
            pinned_builds = self._get_builds(pinned_nvr_list)
            missing_nvrs = [nvr for nvr, build in zip(pinned_nvr_list, pinned_builds) if not build]
            if missing_nvrs:
                raise IOError(f"The following NVRs pinned by 'is' don't exist: {missing_nvrs}")
            for pinned_build in pinned_builds:
                component_builds[pinned_build["name"]] = pinned_build
        return component_builds

    def from_group_deps(self, el_version: int, group_config: Model, rpm_map: Dict[str, RPMMetadata]) -> Dict[str, Dict]:
        """ Returns RPM builds defined in group config dependencies
        :param el_version: RHEL version
        :param group_config: a Model for group config
        :param rpm_map: Map of rpm_distgit_key -> RPMMetadata
        :return: a dict; keys are component names, values are Brew build dicts
        """
        component_builds: Dict[str, Dict] = {}  # rpms pinned to the runtime assembly; keys are rpm component names, values are brew build dicts
        # honor group dependencies
        dep_nvrs = {parse_nvr(dep[f"el{el_version}"])["name"]: dep[f"el{el_version}"] for dep in group_config.dependencies.rpms if dep[f"el{el_version}"]}  # rpms for this rhel version listed in group dependencies; keys are rpm component names, values are nvrs
        if dep_nvrs:
            dep_nvr_list = list(dep_nvrs.values())
            self._logger.info("Found %s NVRs defined in group dependencies. Fetching build infos from Brew...", len(dep_nvr_list))
            dep_builds = self._get_builds(dep_nvr_list)
            missing_nvrs = [nvr for nvr, build in zip(dep_nvr_list, dep_builds) if not build]
            if missing_nvrs:
                raise IOError(f"The following group dependency NVRs don't exist: {missing_nvrs}")
            # Make sure group dependencies have no ART managed rpms.
            art_rpms_in_group_deps = {dep_build["name"] for dep_build in dep_builds} & {meta.rpm_name for meta in rpm_map.values()}
            if art_rpms_in_group_deps:
                raise ValueError(f"attachableGroup dependencies cannot have ART managed RPMs: {art_rpms_in_group_deps}")
            for dep_build in dep_builds:
                component_builds[dep_build["name"]] = dep_build
        return component_builds

    def from_image_member_deps(self, el_version: int, assembly: str, releases_config: Model, image_meta: ImageMetadata, rpm_map: Dict[str, RPMMetadata]) -> Dict[str, Dict]:
        """ Returns RPM builds defined in image member dependencies
        :param el_version: RHEL version
        :param assembly: Assembly name to query. If None, this method will return true latest builds.
        :param releases_config: a Model for releases.yaml
        :param image_meta: An instance of ImageMetadata
        :param rpm_map: Map of rpm_distgit_key -> RPMMetadata
        :return: a dict; keys are component names, values are Brew build dicts
        """
        component_builds: Dict[str, Dict] = {}  # rpms pinned to the runtime assembly; keys are rpm component names, values are brew build dicts

        meta_config = assembly_metadata_config(releases_config, assembly, 'image', image_meta.distgit_key, image_meta.config)
        # honor image member dependencies
        dep_nvrs = {parse_nvr(dep[f"el{el_version}"])["name"]: dep[f"el{el_version}"] for dep in meta_config.dependencies.rpms if dep[f"el{el_version}"]}  # rpms for this rhel version listed in member dependencies; keys are rpm component names, values are nvrs
        if dep_nvrs:
            dep_nvr_list = list(dep_nvrs.values())
            self._logger.info("Found %s NVRs defined in image member '%s' dependencies. Fetching build infos from Brew...", len(dep_nvr_list), image_meta.distgit_key)
            dep_builds = self._get_builds(dep_nvr_list)
            missing_nvrs = [nvr for nvr, build in zip(dep_nvr_list, dep_builds) if not build]
            if missing_nvrs:
                raise IOError(f"The following image member dependency NVRs don't exist: {missing_nvrs}")
            # Make sure image member dependencies have no ART managed rpms.
            art_rpms_in_deps = {dep_build["name"] for dep_build in dep_builds} & {meta.rpm_name for meta in rpm_map.values()}
            if art_rpms_in_deps:
                raise ValueError(f"attachableImage member dependencies cannot have ART managed RPMs: {art_rpms_in_deps}")
            for dep_build in dep_builds:
                component_builds[dep_build["name"]] = dep_build
        return component_builds

    def from_rhcos_deps(self, el_version: int, assembly: str, releases_config: Model, rpm_map: Dict[str, Dict]):
        """ Returns RPM builds defined in RHCOS config dependencies
        :param el_version: RHEL version
        :param assembly: Assembly name to query. If None, this method will return true latest builds.
        :param releases_config: a Model for releases.yaml
        :param rpm_map: Map of rpm_distgit_key -> RPMMetadata
        :return: a dict; keys are component names, values are Brew build dicts
        """
        component_builds: Dict[str, Dict] = {}  # keys are rpm component names, values are brew build dicts
        rhcos_config = assembly_rhcos_config(releases_config, assembly)
        # honor RHCOS dependencies
        # rpms for this rhel version listed in RHCOS dependencies; keys are rpm component names, values are nvrs
        dep_nvrs = {parse_nvr(dep[f"el{el_version}"])["name"]: dep[f"el{el_version}"] for dep in rhcos_config.dependencies.rpms if dep[f"el{el_version}"]}
        if dep_nvrs:
            dep_nvr_list = list(dep_nvrs.values())
            self._logger.info("Found %s NVRs defined in RHCOS dependencies. Fetching build infos from Brew...", len(dep_nvr_list))
            dep_builds = self._get_builds(dep_nvr_list)
            missing_nvrs = [nvr for nvr, build in zip(dep_nvr_list, dep_builds) if not build]
            if missing_nvrs:
                raise IOError(f"The following RHCOS dependency NVRs don't exist: {missing_nvrs}")
            # Make sure RHCOS dependencies have no ART managed rpms.
            art_rpms_in_rhcos_deps = {dep_build["name"] for dep_build in dep_builds} & {meta.rpm_name for meta in rpm_map.values()}
            if art_rpms_in_rhcos_deps:
                raise ValueError(f"attachableGroup dependencies cannot have ART managed RPMs: {art_rpms_in_rhcos_deps}")
            for dep_build in dep_builds:
                component_builds[dep_build["name"]] = dep_build
        return component_builds
