import unittest

import yaml

from elliottlib.assembly import (assembly_basis_event, assembly_group_config,
                                 assembly_metadata_config,
                                 assembly_rhcos_config, merger)
from elliottlib.model import Missing, Model


class TestAssembly(unittest.TestCase):

    def setUp(self) -> None:
        releases_yml = """
releases:
  ART_1:
    assembly:
      members:
        rpms:
        - distgit_key: openshift-kuryr
          metadata:  # changes to make the metadata
            content:
              source:
                git:
                  url: git@github.com:jupierce/kuryr-kubernetes.git
                  branch:
                    target: 1_hash
      group:
        arches:
        - x86_64
        - ppc64le
        - s390x
        advisories:
          image: 11
          extras: 12

  ART_2:
    assembly:
      basis:
        brew_event: 5
      members:
        rpms:
        - distgit_key: openshift-kuryr
          metadata:  # changes to make the metadata
            content:
              source:
                git:
                  url: git@github.com:jupierce/kuryr-kubernetes.git
                  branch:
                    target: 2_hash
      group:
        arches:
        - x86_64
        - s390x
        advisories:
          image: 21

  ART_3:
    assembly:
      basis:
        assembly: ART_2
      group:
        advisories:
          image: 31

  ART_4:
    assembly:
      basis:
        assembly: ART_3
      group:
        advisories!:
          image: 41

  ART_5:
    assembly:
      basis:
        assembly: ART_4
      group:
        arches!:
        - s390x
        advisories!:
          image: 51

  ART_6:
    assembly:
      basis:
        assembly: ART_5
      members:
        rpms:
        - distgit_key: '*'
          metadata:
            content:
              source:
                git:
                  branch:
                    target: customer_6

  ART_7:
    assembly:
      basis:
        brew_event: 5
      members:
        images:
        - distgit_key: openshift-kuryr
          metadata:
            content:
              source:
                git:
                  url: git@github.com:jupierce/kuryr-kubernetes.git
                  branch:
                    target: 1_hash
            is: kuryr-nvr
            dependencies:
              rpms:
              - el7: some-nvr-1
                non_gc_tag: some-tag-1
      group:
        dependencies:
          rpms:
            - el7: some-nvr-3
              non_gc_tag: some-tag-3
      rhcos:
        machine-os-content:
          images:
            x86_64: registry.example.com/rhcos-x86_64:test
        dependencies:
          rpms:
            - el7: some-nvr-4
              non_gc_tag: some-tag-4
            - el8: some-nvr-5
              non_gc_tag: some-tag-4

  ART_8:
    assembly:
      basis:
        assembly: ART_7
      members:
        images:
        - distgit_key: openshift-kuryr
          metadata:
            is: kuryr-nvr2
            dependencies:
              rpms:
              - el7: some-nvr-2
                non_gc_tag: some-tag-2
      group:
        dependencies:
          rpms:
            - el7: some-nvr-4
              non_gc_tag: some-tag-4
      rhcos:
        machine-os-content:
          images: {}
        dependencies:
          rpms:
            - el8: some-nvr-6
              non_gc_tag: some-tag-6

  ART_INFINITE:
    assembly:
      basis:
        assembly: ART_INFINITE
      members:
        rpms:
        - distgit_key: '*'
          metadata:
            content:
              source:
                git:
                  branch:
                    target: customer_6

"""
        self.releases_config = Model(dict_to_model=yaml.safe_load(releases_yml))

    def test_merger(self):
        # First value dominates on primitive
        self.assertEqual(merger(4, 5), 4)
        self.assertEqual(merger('4', '5'), '4')
        self.assertEqual(merger(None, '5'), None)
        self.assertEqual(merger(True, None), True)

        # Dicts are additive
        self.assertEqual(
            merger({'x': 5}, None),
            {'x': 5}
        )

        self.assertEqual(
            merger({'x': 5}, {'y': 6}),
            {'x': 5, 'y': 6}
        )

        # Depth does not matter
        self.assertEqual(
            merger({'r': {'x': 5}}, {'r': {'y': 6}}),
            {'r': {'x': 5, 'y': 6}}
        )

        self.assertEqual(
            merger({'r': {'x': 5, 'y': 7}}, {'r': {'y': 6}}),
            {'r': {'x': 5, 'y': 7}}
        )

        # ? key provides default only
        self.assertEqual(
            merger({'r': {'x': 5, 'y?': 7}}, {'r': {'y': 6}}),
            {'r': {'x': 5, 'y': 6}}
        )

        # ! key dominates completely
        self.assertEqual(
            merger({'r!': {'x': 5}}, {'r': {'y': 6}}),
            {'r': {'x': 5}}
        )

        # Lists are combined, dupes eliminated, and results sorted
        self.assertEqual(
            merger({'r': [1, 2]}, {'r': [1, 3, 4]}),
            {'r': [1, 2, 3, 4]}
        )

        # ! key dominates completely
        self.assertEqual(
            merger({'r!': [1, 2]}, {'r': [3, 4]}),
            {'r': [1, 2]}
        )

    def test_assembly_basis_event(self):
        self.assertEqual(assembly_basis_event(self.releases_config, 'ART_1'), None)
        self.assertEqual(assembly_basis_event(self.releases_config, 'ART_6'), 5)

        try:
            assembly_basis_event(self.releases_config, 'ART_INFINITE')
            self.fail('Expected ValueError on assembly infinite recursion')
        except ValueError:
            pass
        except Exception as e:
            self.fail(f'Expected ValueError on assembly infinite recursion but got: {type(e)}: {e}')

    def test_assembly_group_config(self):

        group_config = Model(dict_to_model={
            'arches': [
                'x86_64'
            ],
            'advisories': {
                'image': 1,
                'extras': 1,
            }
        })

        config = assembly_group_config(self.releases_config, 'ART_1', group_config)
        self.assertEqual(len(config.arches), 3)

        config = assembly_group_config(self.releases_config, 'ART_2', group_config)
        self.assertEqual(len(config.arches), 2)

        # 3 inherits from 2 an only overrides advisory value
        config = assembly_group_config(self.releases_config, 'ART_3', group_config)
        self.assertEqual(len(config.arches), 2)
        self.assertEqual(config.advisories.image, 31)
        self.assertEqual(config.advisories.extras, 1)  # Extras never override, so should be from group_config

        # 4 inherits from 3, but sets "advsories!"
        config = assembly_group_config(self.releases_config, 'ART_4', group_config)
        self.assertEqual(len(config.arches), 2)
        self.assertEqual(config.advisories.image, 41)
        self.assertEqual(config.advisories.extras, Missing)

        # 5 inherits from 4, but sets "advsories!" (overriding 4's !) and "arches!"
        config = assembly_group_config(self.releases_config, 'ART_5', group_config)
        self.assertEqual(len(config.arches), 1)
        self.assertEqual(config.advisories.image, 51)

        config = assembly_group_config(self.releases_config, 'not_defined', group_config)
        self.assertEqual(len(config.arches), 1)

        config = assembly_group_config(self.releases_config, 'ART_7', group_config)
        self.assertEqual(len(config.dependencies.rpms), 1)

        config = assembly_group_config(self.releases_config, 'ART_8', group_config)
        self.assertEqual(len(config.dependencies.rpms), 2)

        try:
            assembly_group_config(self.releases_config, 'ART_INFINITE', group_config)
            self.fail('Expected ValueError on assembly infinite recursion')
        except ValueError:
            pass
        except Exception as e:
            self.fail(f'Expected ValueError on assembly infinite recursion but got: {type(e)}: {e}')

    def test_asembly_metadata_config(self):

        meta_config = Model(dict_to_model={
            'owners': ['kuryr-team@redhat.com'],
            'content': {
                'source': {
                    'git': {
                        'url': 'git@github.com:openshift-priv/kuryr-kubernetes.git',
                        'branch': {
                            'target': 'release-4.8',
                        }
                    },
                    'specfile': 'openshift-kuryr-kubernetes-rhel8.spec'
                }
            },
            'name': 'openshift-kuryr'
        })

        config = assembly_metadata_config(self.releases_config, 'ART_1', 'rpm', 'openshift-kuryr', meta_config)
        # Ensure no loss
        self.assertEqual(config.name, 'openshift-kuryr')
        self.assertEqual(len(config.owners), 1)
        self.assertEqual(config.owners[0], 'kuryr-team@redhat.com')
        # Check that things were overridden
        self.assertEqual(config.content.source.git.url, 'git@github.com:jupierce/kuryr-kubernetes.git')
        self.assertEqual(config.content.source.git.branch.target, '1_hash')

        config = assembly_metadata_config(self.releases_config, 'ART_5', 'rpm', 'openshift-kuryr', meta_config)
        # Ensure no loss
        self.assertEqual(config.name, 'openshift-kuryr')
        self.assertEqual(len(config.owners), 1)
        self.assertEqual(config.owners[0], 'kuryr-team@redhat.com')
        # Check that things were overridden
        self.assertEqual(config.content.source.git.url, 'git@github.com:jupierce/kuryr-kubernetes.git')
        self.assertEqual(config.content.source.git.branch.target, '2_hash')

        config = assembly_metadata_config(self.releases_config, 'ART_6', 'rpm', 'openshift-kuryr', meta_config)
        # Ensure no loss
        self.assertEqual(config.name, 'openshift-kuryr')
        self.assertEqual(len(config.owners), 1)
        self.assertEqual(config.owners[0], 'kuryr-team@redhat.com')
        # Check that things were overridden. 6 changes branches for all rpms
        self.assertEqual(config.content.source.git.url, 'git@github.com:jupierce/kuryr-kubernetes.git')
        self.assertEqual(config.content.source.git.branch.target, 'customer_6')

        config = assembly_metadata_config(self.releases_config, 'ART_8', 'image', 'openshift-kuryr', meta_config)
        # Ensure no loss
        self.assertEqual(config.name, 'openshift-kuryr')
        self.assertEqual(config.content.source.git.url, 'git@github.com:jupierce/kuryr-kubernetes.git')
        self.assertEqual(config.content.source.git.branch.target, '1_hash')
        # Ensure that 'is' comes from ART_8 and not ART_7
        self.assertEqual(config['is'], 'kuryr-nvr2')
        # Ensure that 'dependencies' were accumulate
        self.assertEqual(len(config.dependencies.rpms), 2)

        try:
            assembly_metadata_config(self.releases_config, 'ART_INFINITE', 'rpm', 'openshift-kuryr', meta_config)
            self.fail('Expected ValueError on assembly infinite recursion')
        except ValueError:
            pass
        except Exception as e:
            self.fail(f'Expected ValueError on assembly infinite recursion but got: {type(e)}: {e}')

    def test_assembly_rhcos_config(self):
        rhcos_config = assembly_rhcos_config(self.releases_config, "ART_8")
        self.assertEqual(len(rhcos_config.dependencies.rpms), 3)


if __name__ == '__main__':
    unittest.main()
