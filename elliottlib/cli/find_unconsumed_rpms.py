
import asyncio
from typing import Dict, List, Optional
import click
from elliottlib import brew, exectools, rhcos, util
from elliottlib.assembly import assembly_rhcos_config, AssemblyTypes, assembly_type
from elliottlib.build_finder import BuildFinder

from elliottlib.cli.common import cli, click_coroutine
from elliottlib.imagecfg import ImageMetadata
from elliottlib.runtime import Runtime
import koji


class FindUnconsumedRpms:
    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime

    @staticmethod
    def _list_image_rpms(image_ids: List[int], session: koji.ClientSession) -> List[Optional[List[Dict]]]:
        """ Retrieve RPMs in given images
        :param image_ids: image IDs list
        :param session: instance of Brew session
        :return: a list of Koji/Brew RPM lists
        """
        with session.multicall(strict=True) as m:
            tasks = [m.listRPMs(imageID=image_id) for image_id in image_ids]
        return [task.result for task in tasks]

    @staticmethod
    def _list_archives_by_builds(build_ids: List[int], build_type: str, session: koji.ClientSession) -> List[Optional[List[Dict]]]:
        """ Retrieve information about archives by builds
        :param build_ids: List of build IDs
        :param build_type: build type, such as "image"
        :param session: instance of Brew session
        :return: a list of Koji/Brew archive lists (augmented with "rpms" entries for RPM lists)
        """
        tasks = []
        with session.multicall(strict=True) as m:
            for build_id in build_ids:
                if not build_id:
                    tasks.append(None)
                    continue
                tasks.append(m.listArchives(buildID=build_id, type=build_type))
        archives_list = [task.result if task else None for task in tasks]

        # each archives record contains an archive per arch; look up RPMs for each
        archives = [ar for rec in archives_list for ar in rec or []]
        archives_rpms = FindUnconsumedRpms._list_image_rpms([ar["id"] for ar in archives], session)
        for archive, rpms in zip(archives, archives_rpms):
            archive["rpms"] = rpms
        return archives_list

    def _get_rhcos_rpms(self, koji_api):
        # determine RHCOS build IDs for the runtime assembly
        major, minor = self._runtime.get_major_minor()
        runtime_assembly_type = assembly_type(self._runtime.releases_config, self._runtime.assembly)
        rhcos_config = assembly_rhcos_config(self._runtime.releases_config, self._runtime.assembly)
        rhcos_build_ids = {}
        for brew_arch in self._runtime.group_config.arches:
            for container_conf in rhcos.get_container_configs(self._runtime):
                # first we look at the assembly definition as the source of truth for RHCOS containers
                assembly_rhcos_arch_pullspec = rhcos_config[container_conf.name].images[brew_arch]
                if assembly_rhcos_arch_pullspec:
                    rhcos_build_id, arch = rhcos.get_build_from_pullspec(assembly_rhcos_arch_pullspec)
                    if util.brew_arch_for_go_arch(arch) != brew_arch:
                        raise ValueError(f"Pullspec {assembly_rhcos_arch_pullspec} is not {brew_arch}")
                    rhcos_build_ids[brew_arch] = rhcos_build_id
                    continue
                # for non-stream assemblies we expect explicit config for RHCOS
                if runtime_assembly_type is not AssemblyTypes.STREAM:
                    if container_conf.primary:
                        raise Exception(f'Assembly {self._runtime.assembly} is not type STREAM but no assembly.rhcos.{container_conf.name} image data for {brew_arch}; all RHCOS image data must be populated for this assembly to be valid')
                    # require the primary container at least to be specified, but
                    # allow the edge case where we add an RHCOS container type and
                    # previous assemblies don't specify it
                    continue
                rhcos_build_id = rhcos.latest_build_id(self._runtime, f"{major}.{minor}", brew_arch)
                rhcos_build_ids[brew_arch] = rhcos_build_id

        # list rpms installed in RHCOS builds
        rpm_nvras = set()
        for brew_arch, rhcos_build_id in rhcos_build_ids.items():
            rhcos_rpms = rhcos.get_rpms(self._runtime, rhcos_build_id, f"{major}.{minor}", brew_arch)
            if rhcos_rpms is None:
                raise ValueError("Error getting rhcos rpms")
            for rpm in rhcos_rpms:
                rpm_nvras.add(f"{rpm[0]}-{rpm[2]}-{rpm[3]}.{rpm[4]}")
        tasks = []
        with koji_api.multicall(strict=True) as m:
            for nvra in rpm_nvras:
                tasks.append(m.getRPM(nvra))
        rpm_dicts = [task.result if task else None for task in tasks]
        return rpm_dicts

    async def run(self):
        logger = self._runtime.logger
        koji_api = self._runtime.build_retrying_koji_client(caching=True)

        # Get rpms in RHCOS builds
        rhcos_rpms = self._get_rhcos_rpms(koji_api)

        # Get image builds for the assembly
        image_metas: List[ImageMetadata] = [image for image in self._runtime.image_metas() if not image.base_only and image.is_release]
        logger.info("Fetching Brew builds for %s component(s)...", len(image_metas))
        brew_builds: List[Dict] = await asyncio.gather(*[exectools.to_thread(image.get_latest_build) for image in image_metas])

        logger.info("Retrieve RPMs in %s image build(s)...", len(brew_builds))
        build_archives = FindUnconsumedRpms._list_archives_by_builds([b["id"] for b in brew_builds], "image", koji_api)

        image_rpms = [rpm for ars in build_archives for ar in ars for rpm in ar["rpms"]]

        rpm_build_ids = list({rpm["build_id"] for rpm in rhcos_rpms + image_rpms if rpm})
        logger.info("Retrieve %s RPM build(s)...", len(rpm_build_ids))
        rpm_builds = brew.get_build_objects(rpm_build_ids, koji_api)
        rpm_component_names = {b["name"] for b in rpm_builds}

        # Compare tagged rpms
        replace_vars = self._runtime.group_config.vars.primitive() if self._runtime.group_config.vars else {}
        et_data = self._runtime.get_errata_config(replace_vars=replace_vars)
        tag_pv_map = et_data.get('brew_tag_product_version_mapping')
        finder = BuildFinder(koji_api, logger=logger)
        extra_components = {}
        for tag in tag_pv_map.keys():
            tagged_rpm_builds = finder.from_tag("rpm", tag, inherit=False, assembly=self._runtime.assembly, event=self._runtime.brew_event)
            extra_components[tag] = sorted(tagged_rpm_builds.keys() - rpm_component_names)

        for tag, extras in extra_components.items():
            print(f"* The following Brew packages are tagged into {tag} but not used in any images:")
            for name in extras:
                print(f"\t{name}")


@cli.command('find-unconsumed-rpms', short_help='Find rpms that are not consumed by images or RHCOS')
@click.pass_obj
@click_coroutine
async def find_unconsumed_rpms_cli(runtime: Runtime):
    """ Finds rpms that are tagged into candidate brew tags but not used in images or RHCOS.
    """
    runtime.initialize(mode="both")
    await FindUnconsumedRpms(runtime=runtime).run()
