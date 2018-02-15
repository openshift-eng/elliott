"""

Test the brew related functions/classes

"""

import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import brew

image_build_attached_json = {
    "id": 660050,
    "nvr": "template-service-broker-docker-v3.7.36-2",
    "package": {
        "id": 40328,
        "name": "template-service-broker-docker"
    },
    "released_errata": None,
    "all_errata": [
        {
            "id": 32337,
            "name": "RHBA-2018:32337",
            "status": "NEW_FILES"
        }
    ],
    "rpms_signed": False,
    "files": [
        {
            "id": 2354632,
            "path": "/mnt/redhat/brewroot/packages/template-service-broker-docker/v3.7.36/2/images/docker-image-sha256:c0ccc42e77a2d279cadb285d1bde0e0286f30ac4d7904db4071b59b5fdeac317.x86_64.tar.gz",
            "type": "tar",
            "arch": {
                "id": 13,
                "name": "x86_64"
            }
        }
    ]
}

image_build_unattached_json = {
    "id": 660540,
    "nvr": "cri-o-docker-v3.7.37-1",
    "package": {
        "id": 39891,
        "name": "cri-o-docker"
    },
    "released_errata": None,
    "all_errata": [],
    "rpms_signed": False,
    "files": [
        {
            "id": 2355539,
            "path": "/mnt/redhat/brewroot/packages/cri-o-docker/v3.7.37/1/images/docker-image-sha256:cd8ff09475c390d7cf99d44457e3dac4c70b3f0b59638df97f3d3d5317680954.x86_64.tar.gz",
            "type": "tar",
            "arch": {
                "id": 13,
                "name": "x86_64"
            }
        }
    ]
}

rpm_build_attached_json = {
    "id": 629986,
    "nvr": "coreutils-8.22-21.el7",
    "package": {
        "id": 87,
        "name": "coreutils"
    },
    "released_errata": None,
    "all_errata": [
        {
            "id": 30540,
            "name": "RHBA-2017:30540",
            "status": "REL_PREP"
        }
    ],
    "rpms_signed": True,
    "files": [
        {
            "id": 5256225,
            "path": "/mnt/redhat/brewroot/packages/coreutils/8.22/21.el7/data/signed/fd431d51/src/coreutils-8.22-21.el7.src.rpm",
            "type": "rpm",
            "arch": {
                "id": 24,
                "name": "SRPMS"
            }
        },
        {
            "id": 5256226,
            "path": "/mnt/redhat/brewroot/packages/coreutils/8.22/21.el7/data/signed/fd431d51/ppc/coreutils-8.22-21.el7.ppc.rpm",
            "type": "rpm",
            "arch": {
                "id": 17,
                "name": "ppc"
            }
        },
        {
            "id": 5256227,
            "path": "/mnt/redhat/brewroot/packages/coreutils/8.22/21.el7/data/signed/fd431d51/ppc/coreutils-debuginfo-8.22-21.el7.ppc.rpm",
            "type": "rpm",
            "arch": {
                "id": 17,
                "name": "ppc"
            }
        }
    ]
}

rpm_build_unattached_json = {
    "id": 653686,
    "nvr": "ansible-service-broker-1.0.21-1.el7",
    "package": {
        "id": 38747,
        "name": "ansible-service-broker"
    },
    "released_errata": None,
    "all_errata": [],
    "rpms_signed": False,
    "files": [
        {
            "id": 5446315,
            "path": "/mnt/redhat/brewroot/packages/ansible-service-broker/1.0.21/1.el7/src/ansible-service-broker-1.0.21-1.el7.src.rpm",
            "type": "rpm",
            "arch": {
                "id": 24,
                "name": "SRPMS"
            }
        },
        {
            "id": 5446316,
            "path": "/mnt/redhat/brewroot/packages/ansible-service-broker/1.0.21/1.el7/noarch/ansible-service-broker-selinux-1.0.21-1.el7.noarch.rpm",
            "type": "rpm",
            "arch": {
                "id": 8,
                "name": "noarch"
            }
        }
    ]
}

bogus_build_json = {}

class TestBrew(unittest.TestCase):

    def test_good_attached_brew_image_build(self):
        """We can create and process an attached image Build object"""
        b = brew.Build(nvr='template-service-broker-docker-v3.7.36-2',
                       body=image_build_attached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('template-service-broker-docker-v3.7.36-2', b.nvr)
        self.assertEqual('image', b.kind)
        self.assertEqual('tar', b.file_type)
        self.assertTrue(b.attached)

    def test_good_unattached_brew_image_build(self):
        """We can create and process an unattached image Build object"""
        b = brew.Build(nvr='cri-o-docker-v3.7.37-1',
                       body=image_build_unattached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('cri-o-docker-v3.7.37-1', b.nvr)
        self.assertEqual('image', b.kind)
        self.assertEqual('tar', b.file_type)
        self.assertFalse(b.attached)

    def test_good_attached_brew_rpm_build(self):
        """We can create and process an attached rpm Build object"""
        b = brew.Build(nvr='coreutils-8.22-21.el7',
                       body=rpm_build_attached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('coreutils-8.22-21.el7', b.nvr)
        self.assertEqual('rpm', b.kind)
        self.assertEqual('rpm', b.file_type)
        self.assertTrue(b.attached)

    def test_good_unattached_brew_rpm_build(self):
        """We can create and process an unattached rpm Build object"""
        b = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
                       body=rpm_build_unattached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('ansible-service-broker-1.0.21-1.el7', b.nvr)
        self.assertEqual('rpm', b.kind)
        self.assertEqual('rpm', b.file_type)
        self.assertFalse(b.attached)

    def test_build_sorting(self):
        """Ensure we can sort a list of builds"""
        b1 = brew.Build(nvr='abcd-1.0.0')
        b2 = brew.Build(nvr='zyxw-1.0.0')
        # Same one as before for equality
        b3 = brew.Build(nvr='zyxw-1.0.0')

        self.assertGreater(b2, b1)
        self.assertLess(b1, b2)
        self.assertEqual(b2, b3)

if __name__ == '__main__':
    unittest.main()
