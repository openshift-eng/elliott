import unittest
from unittest import mock
import json
import errata_tool
import koji
from elliottlib import tarball_sources


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
                             ["logging-eventrouter-container-v3.11.141-2", "logging-curator5-container-v3.11.141-2", "atomic-openshift-cluster-autoscaler-container-v3.11.141-2", "logging-fluentd-container-v3.11.141-2", "ose-ovn-kubernetes-container-v3.11.141-2", "logging-kibana5-container-v3.11.141-2", "efs-provisioner-container-v3.11.141-2", "csi-livenessprobe-container-v3.11.141-2", "csi-attacher-container-v3.11.141-2", "atomic-openshift-node-problem-detector-container-v3.11.141-2", "openshift-manila-provisioner-container-v3.11.141-2", "csi-provisioner-container-v3.11.141-2", "openshift-enterprise-apb-tools-container-v3.11.141-2", "atomic-openshift-descheduler-container-v3.11.141-2", "metrics-schema-installer-container-v3.11.141-2", "golang-github-prometheus-node_exporter-container-v3.11.141-2", "logging-elasticsearch5-container-v3.11.141-2", "golang-github-prometheus-alertmanager-container-v3.11.141-2", "registry-console-container-v3.11.141-2", "csi-driver-registrar-container-v3.11.141-2", "golang-github-openshift-oauth-proxy-container-v3.11.141-1", "snapshot-controller-container-v3.11.141-2", "snapshot-provisioner-container-v3.11.141-2", "openshift-enterprise-asb-container-v3.11.141-2", "metrics-heapster-container-v3.11.141-2", "openshift-local-storage-container-v3.11.141-2", "openshift-enterprise-apb-base-container-v3.11.141-2", "aos3-installation-container-v3.11.141-2", "golang-github-prometheus-prometheus-container-v3.11.141-2", "metrics-hawkular-openshift-agent-container-v3.11.141-2", "automation-broker-apb-v3.11.141-2", "configmap-reload-container-v3.11.141-2", "cluster-monitoring-operator-container-v3.11.141-2", "grafana-container-v3.11.141-2", "kube-state-metrics-container-v3.11.141-2", "atomic-openshift-metrics-server-container-v3.11.141-2", "prometheus-operator-container-v3.11.141-2", "kube-rbac-proxy-container-v3.11.141-2", "prometheus-config-reloader-container-v3.11.141-2", "operator-lifecycle-manager-container-v3.11.141-2", "openshift-enterprise-console-container-v3.11.141-2", "openshift-enterprise-hypershift-container-v3.11.141-2", "openshift-enterprise-egress-dns-proxy-container-v3.11.141-2", "openshift-enterprise-hyperkube-container-v3.11.141-2", "openshift-enterprise-cli-container-v3.11.141-2", "openshift-enterprise-mysql-apb-v3.11.141-2", "origin-web-console-server-container-v3.11.141-2", "openshift-enterprise-mariadb-apb-v3.11.141-2", "openshift-enterprise-postgresql-apb-v3.11.141-2", "openshift-enterprise-mediawiki-apb-v3.11.141-2", "template-service-broker-container-v3.11.141-2", "openshift-enterprise-tests-container-v3.11.141-2", "ose-egress-http-proxy-container-v3.11.141-2", "openshift-enterprise-cluster-capacity-container-v3.11.141-2", "openshift-enterprise-service-catalog-container-v3.11.141-2", "openshift-enterprise-registry-container-v3.11.141-2", "openshift-enterprise-keepalived-ipfailover-container-v3.11.141-2", "openshift-enterprise-pod-container-v3.11.141-2", "openshift-enterprise-egress-router-container-v3.11.141-2", "jenkins-subordinate-base-rhel7-container-v3.11.141-2", "openshift-enterprise-recycler-container-v3.11.141-2", "openshift-enterprise-builder-container-v3.11.141-2", "openshift-enterprise-haproxy-router-container-v3.11.141-2", "openshift-enterprise-deployer-container-v3.11.141-2", "jenkins-agent-nodejs-8-rhel7-container-v3.11.141-2", "jenkins-subordinate-nodejs-rhel7-container-v3.11.141-2", "jenkins-subordinate-maven-rhel7-container-v3.11.141-2", "openshift-enterprise-mediawiki-container-v3.11.141-3", "jenkins-agent-maven-35-rhel7-container-v3.11.141-3", "metrics-cassandra-container-v3.11.141-3", "openshift-jenkins-2-container-v3.11.141-3", "metrics-hawkular-metrics-container-v3.11.141-3", "openshift-enterprise-container-v3.11.141-3", "openshift-enterprise-node-container-v3.11.141-3"]}
            advisory.errata_builds = errata_builds
            expected = [("logging-fluentd-container-v3.11.141-2", "RHOSE", "RHEL-7-OSE-3.11")]
            actual = tarball_sources.find_builds_from_advisory(advisory.errata_id, ["logging-fluentd-container"])
            self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
