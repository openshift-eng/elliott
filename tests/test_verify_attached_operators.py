import json, yaml
import unittest
import os
from unittest.mock import MagicMock, patch
from pathlib import Path

from elliottlib.cli import verify_attached_operators_cli as vaocli
from elliottlib.exceptions import BrewBuildException


class TestVerifyAttachedOperators(unittest.TestCase):

    def setUp(self):
        self.respath = Path(os.path.dirname(__file__), 'resources')

    @patch("elliottlib.exectools.cmd_assert", autospec=True)
    def test_nvr_for_operand_pullspec(self, mock_cmd):
        runtime = MagicMock()
        img_info = dict(config=dict(config=dict(Labels={
            "com.redhat.component": "csi-provisioner-container",
            "release": "42",
            "version": "v4.9.0",
        })))
        mock_cmd.return_value = (json.dumps(img_info), "")

        self.assertEqual(
            "csi-provisioner-container-v4.9.0-42",
            vaocli._nvr_for_operand_pullspec(runtime, "something")
        )

    @patch("requests.get", autospec=True)
    def test_download_bundle_csv(self, mock_get_req):
        bundle_build = dict(
            package_name="ose-ptp-operator-metadata-container",
            version="v4.11.0.202303240327.p0.g88b8e8d.assembly.stream",
            release="1",
            nvr="ose-ptp-operator-metadata-container-v4.11.0.202303240327.p0.g88b8e8d.assembly.stream-1",
        )
        fixture_path = self.respath.joinpath('test_verify_attached_operators', 'operator_manifests.zip')
        mock_get_req.return_value = MagicMock(
            status_code=200,
            content=Path(fixture_path).read_bytes(),
        )

        self.assertEqual(
            "ptp-operator.4.11.0-202303240327",
            vaocli._download_bundle_csv(bundle_build)['metadata']['name']
        )

    @patch("elliottlib.cli.verify_attached_operators_cli.red_print")  # suppress output
    def test_validate_csvs(self, mock_red_print):
        bundles = [
            dict(nvr="spam", csv=dict(
                metadata={"name": "spam.v4-202303240327"},
                spec={"version": "v4.12.0-202303240327"},
            )),
            dict(nvr="eggs", csv=dict(
                metadata={"name": "eggs.v4-notimestamp"},
                spec={"version": "v4.12.0-202303240327"},
            )),
            dict(nvr="baked-beans", csv=dict(
                metadata={"name": "bakedbeans.v4-202303240327"},
            )),
        ]
        self.assertEqual({"eggs", "baked-beans"}, vaocli._validate_csvs(bundles))

    @patch("elliottlib.brew.get_brew_build", autospec=True)
    def test_get_attached_advisory_ids(self, mock_gbb):
        mock_gbb.return_value = MagicMock(all_errata=[
            {'id': 42, 'name': 'RHSA-2022:7400', 'status': 'DROPPED_NO_SHIP'},
            {'id': 104603, 'name': 'RHSA-2022:7401', 'status': 'SHIPPED_LIVE'},
        ])
        self.assertEqual({104603}, vaocli._get_attached_advisory_ids("nvr"), "contains only shipped")

    @patch("elliottlib.errata.get_cached_image_cdns", autospec=True)
    def test_get_cdn_repos(self, mock_gci_cdns):
        mock_gci_cdns.return_value = {
            'nvr1': {'docker': {'target': {
                'external_repos': {
                    'openshift4/ose-metallb-operator': "{metadata}",
                    'openshift4/ose-metallb-rhel8-operator': "{metadata}",
                },
                'repos': {  # not actually used, just for context
                    'redhat-openshift4-ose-metallb-operator': "{metadata}",
                    'redhat-openshift4-ose-metallb-rhel8-operator': "{metadata}",
                },
            }}},
            'nvr2': {'docker': {'target': {
                'external_repos': {
                    'openshift4/ose-some-other-operator': "{metadata}",
                },
            }}},
        }
        self.assertEqual(
            {'openshift4/ose-metallb-operator', 'openshift4/ose-metallb-rhel8-operator'},
            vaocli._get_cdn_repos({42}, 'nvr1'),
            "returns external repos for nvr1 and not nvr2"
        )

    @patch("elliottlib.cli.verify_attached_operators_cli.red_print")  # suppress output
    @patch("elliottlib.cli.verify_attached_operators_cli.green_print")  # suppress output
    @patch("elliottlib.cli.verify_attached_operators_cli._nvr_for_operand_pullspec")
    @patch("elliottlib.cli.verify_attached_operators_cli._get_attached_advisory_ids")
    @patch("elliottlib.cli.verify_attached_operators_cli._get_cdn_repos")
    def test_missing_references(self, mock_gcdnr, mock_gadids, mock_nvr, mock_green, mock_red):
        out = []
        mock_red.side_effect = mock_green.side_effect = lambda arg: out.append(arg)
        bundles = yaml.safe_load("""
            - nvr: bundle-nvr-1-0
              csv:
                apiVersion: operators.coreos.com/v1alpha1
                kind: ClusterServiceVersion
                metadata:
                  name: ptp-operator.4.11.0-202303240327
                spec:
                  version: 4.11.0-202303240327
                  relatedImages:
                  - image: registry.redhat.io/openshift4/ose-kube-rbac-proxy@sha256:feedface
                    name: ose-kube-rbac-proxy
        """)  # obviously, much omitted
        mock_nvr.return_value = "operand-nvr-1-0"
        mock_gadids.return_value = set()
        mock_gcdnr.return_value = set()
        self.assertEqual({"operand-nvr-1-0"}, vaocli._missing_references(None, bundles, set(), False))
        self.assertIn("not shipped or attached", out.pop())

        # when we say the operand digest has been shipped, but give no CDNs
        vaocli._missing_references(None, bundles, {"sha256:feedface"}, False)
        self.assertIn("does not have any CDN repos", out.pop(), "should be found in shipped")

        # when we say it's attached to some advisory, but give no CDNs
        mock_gadids.return_value = {42}
        vaocli._missing_references(None, bundles, set(), False)
        self.assertIn("does not have any CDN repos", out.pop(), "should be found in attached")

        # when we give a CDN but it doesn't match the bundle pullspec
        mock_gcdnr.return_value = {"openshift4/ose-kube-rbac-proxy-NOT"}
        vaocli._missing_references(None, bundles, set(), False)
        self.assertIn("needs CDN repo 'openshift4/ose-kube-rbac-proxy'", out.pop())

        # when the CDN does match
        mock_gcdnr.return_value = {"openshift4/ose-kube-rbac-proxy"}
        self.assertFalse(
            vaocli._missing_references(None, bundles, {"sha256:feedface"}, False),
            "should succeed")
        self.assertIn("shipped/shipping", out.pop())

        # ... but we omit advisories that weren't specified
        vaocli._missing_references(None, bundles, set(), True)
        self.assertIn("only found in omitted advisory {42}", out.pop())

        # when not excluding separate advisories, it is finally found
        self.assertFalse(
            vaocli._missing_references(None, bundles, set(), False),
            "when not omitted")
        self.assertIn("attached to separate advisory {42}", out.pop())

        # when looking up the operand NVR in errata-tool fails
        mock_gadids.side_effect = BrewBuildException("no such build")
        vaocli._missing_references(None, bundles, set(), False)
        self.assertIn("failed to look up in errata-tool", out.pop())
