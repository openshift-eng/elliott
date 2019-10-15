from __future__ import unicode_literals, print_function
import unittest
import mock
import json
import errata_tool
import koji
from elliottlib import tarball_sources
import io
import tarfile


class TarballSourcesTestCase(unittest.TestCase):

    def test_find_builds_from_advisory(self):
        with self.assertRaises(errata_tool.ErrataException), mock.patch("errata_tool.Erratum", side_effect=errata_tool.ErrataException):
            tarball_sources.find_builds_from_advisory(0, ["logging-fluentd-container"])

        with mock.patch("errata_tool.Erratum", spec=True) as MockErratum:
            advisory = MockErratum.return_value
            advisory.errata_id = 45606
            advisory.errata_name = "RHBA-2019:2581-02"
            advisory.errata_state = 'SHIPPED_LIVE'
            advisory._product = 'RHOSE'
            advisory.synopsis = "dummy synopsis"
            errata_builds = {"RHEL-7-OSE-3.11":
                             ["logging-eventrouter-container-v3.11.141-2", "logging-curator5-container-v3.11.141-2", "atomic-openshift-cluster-autoscaler-container-v3.11.141-2", "logging-fluentd-container-v3.11.141-2", "ose-ovn-kubernetes-container-v3.11.141-2", "logging-kibana5-container-v3.11.141-2", "efs-provisioner-container-v3.11.141-2", "csi-livenessprobe-container-v3.11.141-2", "csi-attacher-container-v3.11.141-2", "atomic-openshift-node-problem-detector-container-v3.11.141-2", "openshift-manila-provisioner-container-v3.11.141-2", "csi-provisioner-container-v3.11.141-2", "openshift-enterprise-apb-tools-container-v3.11.141-2", "atomic-openshift-descheduler-container-v3.11.141-2", "metrics-schema-installer-container-v3.11.141-2", "golang-github-prometheus-node_exporter-container-v3.11.141-2", "logging-elasticsearch5-container-v3.11.141-2", "golang-github-prometheus-alertmanager-container-v3.11.141-2", "registry-console-container-v3.11.141-2", "csi-driver-registrar-container-v3.11.141-2", "golang-github-openshift-oauth-proxy-container-v3.11.141-1", "snapshot-controller-container-v3.11.141-2", "snapshot-provisioner-container-v3.11.141-2", "openshift-enterprise-asb-container-v3.11.141-2", "metrics-heapster-container-v3.11.141-2", "openshift-local-storage-container-v3.11.141-2", "openshift-enterprise-apb-base-container-v3.11.141-2", "aos3-installation-container-v3.11.141-2", "golang-github-prometheus-prometheus-container-v3.11.141-2", "metrics-hawkular-openshift-agent-container-v3.11.141-2", "automation-broker-apb-v3.11.141-2", "configmap-reload-container-v3.11.141-2", "cluster-monitoring-operator-container-v3.11.141-2", "grafana-container-v3.11.141-2", "kube-state-metrics-container-v3.11.141-2", "atomic-openshift-metrics-server-container-v3.11.141-2", "prometheus-operator-container-v3.11.141-2", "kube-rbac-proxy-container-v3.11.141-2", "prometheus-config-reloader-container-v3.11.141-2", "operator-lifecycle-manager-container-v3.11.141-2", "openshift-enterprise-console-container-v3.11.141-2", "openshift-enterprise-hypershift-container-v3.11.141-2", "openshift-enterprise-egress-dns-proxy-container-v3.11.141-2", "openshift-enterprise-hyperkube-container-v3.11.141-2", "openshift-enterprise-cli-container-v3.11.141-2", "openshift-enterprise-mysql-apb-v3.11.141-2", "origin-web-console-server-container-v3.11.141-2", "openshift-enterprise-mariadb-apb-v3.11.141-2", "openshift-enterprise-postgresql-apb-v3.11.141-2", "openshift-enterprise-mediawiki-apb-v3.11.141-2", "template-service-broker-container-v3.11.141-2", "openshift-enterprise-tests-container-v3.11.141-2", "ose-egress-http-proxy-container-v3.11.141-2", "openshift-enterprise-cluster-capacity-container-v3.11.141-2", "openshift-enterprise-service-catalog-container-v3.11.141-2", "openshift-enterprise-registry-container-v3.11.141-2", "openshift-enterprise-keepalived-ipfailover-container-v3.11.141-2", "openshift-enterprise-pod-container-v3.11.141-2", "openshift-enterprise-egress-router-container-v3.11.141-2", "jenkins-slave-base-rhel7-container-v3.11.141-2", "openshift-enterprise-recycler-container-v3.11.141-2", "openshift-enterprise-builder-container-v3.11.141-2", "openshift-enterprise-haproxy-router-container-v3.11.141-2", "openshift-enterprise-deployer-container-v3.11.141-2", "jenkins-agent-nodejs-8-rhel7-container-v3.11.141-2", "jenkins-slave-nodejs-rhel7-container-v3.11.141-2", "jenkins-slave-maven-rhel7-container-v3.11.141-2", "openshift-enterprise-mediawiki-container-v3.11.141-3", "jenkins-agent-maven-35-rhel7-container-v3.11.141-3", "metrics-cassandra-container-v3.11.141-3", "openshift-jenkins-2-container-v3.11.141-3", "metrics-hawkular-metrics-container-v3.11.141-3", "openshift-enterprise-container-v3.11.141-3", "openshift-enterprise-node-container-v3.11.141-3"]}
            advisory.errata_builds = errata_builds
            expected = [("logging-fluentd-container-v3.11.141-2", "RHOSE", "RHEL-7-OSE-3.11")]
            actual = tarball_sources.find_builds_from_advisory(advisory.errata_id, ["logging-fluentd-container"])
            self.assertEqual(actual, expected)

    def test_get_builds_from_brew(self):
        # koji.ClientSession.multiCall
        build_nvrs = [
            "logging-fluentd-container-v3.11.141-2",
            "logging-fluentd-container-v4.1.14-201908291507",
            "logging-fluentd-container-v4.1.15-201909041605",
        ]
        build_infos = {
            "logging-fluentd-container-v3.11.141-2": {"cg_id": None, "package_name": "logging-fluentd-container", "extra": {"submitter": "osbs", "image": {"media_types": ["application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"], "help": None, "index": {"pull": ["brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift3/ose-logging-fluentd@sha256:1df5eacdd98923590afdc85330aaac0488de96e991b24a7f4cb60113b7a66e80", "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift3/ose-logging-fluentd:v3.11.141-2"], "digests": {"application/vnd.docker.distribution.manifest.list.v2+json": "sha256:1df5eacdd98923590afdc85330aaac0488de96e991b24a7f4cb60113b7a66e80"}, "tags": ["v3.11.141-2"]}, "autorebuild": False, "isolated": False, "yum_repourls": ["http://pkgs.devel.redhat.com/cgit/containers/logging-fluentd/plain/.oit/signed.repo?h=rhaos-3.11-rhel-7"], "parent_build_id": 955726, "parent_images": ["openshift/ose-base:rhel7"], "parent_image_builds": {"openshift/ose-base:rhel7": {"id": 955726, "nvr": "openshift-enterprise-base-container-v4.0-201908250221"}}}, "container_koji_task_id": 23188768}, "creation_time": "2019-08-26 07:34:32.613833", "completion_time": "2019-08-26 07:34:31", "package_id": 67151, "cg_name": None, "id": 956245, "build_id": 956245, "epoch": None, "source": "git://pkgs.devel.redhat.com/containers/logging-fluentd#7f4bcdc798fd72414a29dc1010c448e1ed52f591", "state": 1, "version": "v3.11.141", "completion_ts": 1566804871.0, "owner_id": 4078, "owner_name": "ocp-build/buildvm.openshift.eng.bos.redhat.com", "nvr": "logging-fluentd-container-v3.11.141-2", "start_time": "2019-08-26 07:03:41", "creation_event_id": 26029088, "start_ts": 1566803021.0, "volume_id": 0, "creation_ts": 1566804872.61383, "name": "logging-fluentd-container", "task_id": None, "volume_name": "DEFAULT", "release": "2"},
            "logging-fluentd-container-v4.1.14-201908291507": {"cg_id": None, "package_name": "logging-fluentd-container", "extra": {"submitter": "osbs", "image": {"media_types": ["application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"], "help": None, "index": {"unique_tags": ["rhaos-4.1-rhel-7-containers-candidate-94076-20190829211225"], "pull": ["brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd@sha256:7503f828aaf80e04b2aaab0b88626b97a20e5600ba75fef8b764e02cc1164a7c", "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd:v4.1.14-201908291507"], "floating_tags": ["latest", "v4.1.14", "v4.1.14.20190829.150756", "v4.1"], "digests": {"application/vnd.docker.distribution.manifest.list.v2+json": "sha256:7503f828aaf80e04b2aaab0b88626b97a20e5600ba75fef8b764e02cc1164a7c"}, "tags": ["v4.1.14-201908291507"]}, "autorebuild": False, "isolated": False, "yum_repourls": ["http://pkgs.devel.redhat.com/cgit/containers/logging-fluentd/plain/.oit/signed.repo?h=rhaos-4.1-rhel-7"], "parent_build_id": 958278, "parent_images": ["rhscl/ruby-25-rhel7:latest", "openshift/ose-base:ubi7"], "parent_image_builds": {"openshift/ose-base:ubi7": {"id": 958278, "nvr": "openshift-enterprise-base-container-v4.0-201908290538"}, "rhscl/ruby-25-rhel7:latest": {"id": 957642, "nvr": "rh-ruby25-container-2.5-50"}}}, "container_koji_task_id": 23241046}, "creation_time": "2019-08-29 21:42:46.062037", "completion_time": "2019-08-29 21:42:44", "package_id": 67151, "cg_name": None, "id": 958765, "build_id": 958765, "epoch": None, "source": "git://pkgs.devel.redhat.com/containers/logging-fluentd#ecac10b38f035ea2f9ea62b9efa63c051667ebbb", "state": 1, "version": "v4.1.14", "completion_ts": 1567114964.0, "owner_id": 4078, "owner_name": "ocp-build/buildvm.openshift.eng.bos.redhat.com", "nvr": "logging-fluentd-container-v4.1.14-201908291507", "start_time": "2019-08-29 21:12:51", "creation_event_id": 26063093, "start_ts": 1567113171.0, "volume_id": 0, "creation_ts": 1567114966.06204, "name": "logging-fluentd-container", "task_id": None, "volume_name": "DEFAULT", "release": "201908291507"},
            "logging-fluentd-container-v4.1.15-201909041605": {"cg_id": None, "package_name": "logging-fluentd-container", "extra": {"submitter": "osbs", "image": {"media_types": ["application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"], "help": None, "index": {"unique_tags": ["rhaos-4.1-rhel-7-containers-candidate-96970-20190904214308"], "pull": ["brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd@sha256:1ce1555b58982a29354c293948ee6c788743a08f39a0c530be791cb9bdaf4189", "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd:v4.1.15-201909041605"], "floating_tags": ["latest", "v4.1.15", "v4.1", "v4.1.15.20190904.160545"], "digests": {"application/vnd.docker.distribution.manifest.list.v2+json": "sha256:1ce1555b58982a29354c293948ee6c788743a08f39a0c530be791cb9bdaf4189"}, "tags": ["v4.1.15-201909041605"]}, "autorebuild": False, "isolated": False, "yum_repourls": ["http://pkgs.devel.redhat.com/cgit/containers/logging-fluentd/plain/.oit/signed.repo?h=rhaos-4.1-rhel-7"], "parent_build_id": 961131, "parent_images": ["rhscl/ruby-25-rhel7:latest", "openshift/ose-base:ubi7"], "parent_image_builds": {"openshift/ose-base:ubi7": {"id": 961131, "nvr": "openshift-enterprise-base-container-v4.0-201909040323"}, "rhscl/ruby-25-rhel7:latest": {"id": 957642, "nvr": "rh-ruby25-container-2.5-50"}}}, "container_koji_task_id": 23365465}, "creation_time": "2019-09-04 22:17:36.432110", "completion_time": "2019-09-04 22:17:35", "package_id": 67151, "cg_name": None, "id": 962144, "build_id": 962144, "epoch": None, "source": "git://pkgs.devel.redhat.com/containers/logging-fluentd#31cf3d4264dabb8892fb4b5921e5ff4d5d0ab2de", "state": 1, "version": "v4.1.15", "completion_ts": 1567635455.0, "owner_id": 4078, "owner_name": "ocp-build/buildvm.openshift.eng.bos.redhat.com", "nvr": "logging-fluentd-container-v4.1.15-201909041605", "start_time": "2019-09-04 21:43:32", "creation_event_id": 26176078, "start_ts": 1567633412.0, "volume_id": 0, "creation_ts": 1567635456.43211, "name": "logging-fluentd-container", "task_id": None, "volume_name": "DEFAULT", "release": "201909041605"},
        }

        def fake_get_build(nvr):
            return build_infos[nvr]

        with mock.patch("koji.ClientSession", spec=True) as MockSession:
            session = MockSession()
            session.getBuild = mock.MagicMock(side_effect=fake_get_build)
            expected = build_infos.values()
            actual = tarball_sources.get_builds_from_brew(session, build_nvrs)
            self.assertListEqual(list(actual), expected)

    def test_archive_lookaside_sources(self):
        repo_url = "git://pkgs.devel.redhat.com/rpms/openshift-clients"
        sources_file = io.BytesIO(b"2ba370dd5e06259ec4fa3b22c50ad2f9  openshift-clients-git-1.c8c7aaa.tar.gz")
        prefix = "openshift-clients-git-1.c8c7aaa/"
        tarball = tarfile.open(fileobj=io.BytesIO(), mode="w:gz")
        buffer = b"1234567890abedef"

        def fake_download_lookaside_source(filename, hash, fileobj, session=None):
            fileobj.write(buffer)
            fileobj.flush()
            return len(buffer)
        with mock.patch("elliottlib.distgit.DistGitRepo.download_lookaside_source", side_effect=fake_download_lookaside_source):
            tarball_sources.archive_lookaside_sources(repo_url, sources_file, tarball, "openshift-clients-git-1.c8c7aaa/")
            self.assertEqual(len(buffer), tarball.getmember(prefix + "openshift-clients-git-1.c8c7aaa.tar.gz").size)


if __name__ == "__main__":
    unittest.main()
