

######################################################################
# PRIMARILY used by errata_test:

example_erratum_filtered_list = [
    {
        "id": 32964,
        "type": "RHBA",
        "text_only": False,
        "advisory_name": "RHBA-2018:0476",
        "synopsis": "Red Hat OpenShift Enterprise 3.7, 3.6, 3.5, 3.4, and 3.3 images update",
        "revision": 6,
        "status": "IN_PUSH",
        "security_impact": "None",
        "respin_count": 1,
        "pushcount": 0,
        "content_types": [
            "docker"
        ],
        "timestamps": {
            "issue_date": "2018-03-08T14:07:14Z",
            "update_date": "2018-03-08T14:07:14Z",
            "release_date": "2018-03-12T00:00:00Z",
            "status_time": "2018-03-13T14:17:34Z",
            "security_sla": None,
            "created_at": "2018-03-08T14:07:14Z",
            "updated_at": "2018-03-13T14:17:34Z"
        },
        "flags": {
            "text_ready": False,
            "mailed": False,
            "pushed": False,
            "published": False,
            "deleted": False,
            "qa_complete": True,
            "rhn_complete": False,
            "doc_complete": True,
            "rhnqa": True,
            "closed": False,
            "sign_requested": False,
            "embargo_undated": False
        },
        "product": {
            "id": 79,
            "name": "Red Hat OpenShift Enterprise",
            "short_name": "RHOSE"
        },
        "release": {
            "id": 436,
            "name": "RHOSE ASYNC"
        },
        "people": {
            "assigned_to": "dma@redhat.com",
            "reporter": "smunilla@redhat.com",
            "qe_group": "OpenShift QE",
            "docs_group": "Default",
            "doc_reviewer": "adellape@redhat.com",
            "devel_group": "Default",
            "package_owner": "smunilla@redhat.com"
        },
        "content": {
            "topic": "An update is now available for Red Hat OpenShift Container Platform 3.7, 3.6, 3.5, 3.4, and 3.3.",
            "description": "OpenShift Container Platform by Red Hat is the company's cloud computing Platform-as-a-Service (PaaS) solution designed for on-premise or private cloud deployments.\n\nThis advisory contains the container images for this release. See the following advisory for the RPM packages and full list of security fixes for this release:\n\nhttps://access.redhat.com/errata/RHSA-2018:0475\n\nThis update contains the following images:\n\nopenshift3/ose:v3.3.1.46.11-20\nopenshift3/node:v3.3.1.46.11-21\n\nopenshift3/ose:v3.4.1.44.38-20\nopenshift3/node:v3.4.1.44.38-21\n\nopenshift3/node:v3.5.5.31.48-20\n\nopenshift3/node:v3.6.173.0.96-20\n\nopenshift3/node:v3.7.23-21\n\nAll OpenShift Container Platform 3.7, 3.6, 3.5, 3.4, and 3.3 users are advised to upgrade to these updated images.",
            "solution": "For details on how to apply this update, which includes the changes described in this advisory, refer to:\n\nhttps://access.redhat.com/articles/11258",
            "keywords": ""
        }
    },
    {
        "id": 32916,
        "type": "RHBA",
        "text_only": False,
        "advisory_name": "RHBA-2018:32916",
        "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
        "revision": 1,
        "status": "NEW_FILES",
        "security_impact": "None",
        "respin_count": 0,
        "pushcount": 0,
        "content_types": [],
        "timestamps": {
            "issue_date": "2018-03-02T15:19:08Z",
            "update_date": "2018-03-02T15:19:08Z",
            "release_date": None,
            "status_time": "2018-03-02T15:19:08Z",
            "security_sla": None,
            "created_at": "2018-03-02T15:19:08Z",
            "updated_at": "2018-03-07T20:47:23Z"
        },
        "flags": {
            "text_ready": False,
            "mailed": False,
            "pushed": False,
            "published": False,
            "deleted": False,
            "qa_complete": False,
            "rhn_complete": False,
            "doc_complete": False,
            "rhnqa": False,
            "closed": False,
            "sign_requested": False,
            "embargo_undated": False
        },
        "product": {
            "id": 79,
            "name": "Red Hat OpenShift Enterprise",
            "short_name": "RHOSE"
        },
        "release": {
            "id": 436,
            "name": "RHOSE ASYNC"
        },
        "people": {
            "assigned_to": "wsun@redhat.com",
            "reporter": "tbielawa@redhat.com",
            "qe_group": "OpenShift QE",
            "docs_group": "Default",
            "doc_reviewer": "docs-errata-list@redhat.com",
            "devel_group": "Default",
            "package_owner": "smunilla@redhat.com"
        },
        "content": {
            "topic": "Red Hat OpenShift Container Platform releases 3.5.z are now available with updates to packages and images that fix several bugs and add enhancements.",
            "description": "Red Hat OpenShift Container Platform is the company's cloud computing Platform-as-a-Service (PaaS) solution designed for on-premise or private cloud deployments.\n\nThis advisory contains the RPM packages for Red Hat OpenShift Container Platform 3.5.z. See the following advisory for the container images for this release:\n\nhttps://access.redhat.com/errata/RHBA-2018:0114\n\nSpace precludes documenting all of the bug fixes and enhancements in this advisory. See the following Release Notes documentation, which will be updated shortly for this release, for details about these changes:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nAll OpenShift Container Platform 3.5 users are advised to upgrade to these updated packages and images.",
            "solution": "Before applying this update, make sure all previously released errata relevant to your system have been applied.\n\nFor OpenShift Container Platform 3.5 see the following documentation, which will be updated shortly for release 3.5.z, for important instructions on how to upgrade your cluster and fully apply this asynchronous errata update:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nThis update is available via the Red Hat Network. Details on how to use the Red Hat Network to apply this update are available at https://access.redhat.com/articles/11258.",
            "keywords": ""
        }
    }
]


example_erratum = {
    "diffs": {},
    "jira_issues": {
        "jira_issues": [],
        "id_field": "key",
        "id_prefix": "jira:",
        "idsfixed": [],
        "to_fetch": [],
        "type": "jira_issues",
        "errata": {
            "rhba": {
                "rating": 0,
                "rhnqa": 0,
                "state_machine_rule_set_id": None,
                "current_tps_run": None,
                "updated_at": "2018-03-07T20:47:23Z",
                "current_state_index_id": 204419,
                "is_brew": 1,
                "pushed": 0,
                "devel_responsibility_id": 3,
                "docs_responsibility_id": 1,
                "rhn_complete": 0,
                "rhnqa_shadow": 0,
                "actual_ship_date": None,
                "sign_requested": 0,
                "id": 32916,
                "update_date": "2018-03-02T15:19:08Z",
                "is_batch_blocker": False,
                "qa_complete": 0,
                "severity": "normal",
                "supports_multiple_product_destinations": True,
                "status_updated_at": "2018-03-02T15:19:08Z",
                "published_shadow": 0,
                "priority": "normal",
                "is_valid": 1,
                "manager_id": 3001032,
                "closed": 0,
                "batch_id": None,
                "security_impact": "None",
                "revision": 1,
                "status": "NEW_FILES",
                "publish_date_override": "2019-01-01T00:00:00Z",
                "text_ready": 0,
                "errata_id": 32916,
                "deleted": 0,
                "request_rcm_push_comment_id": None,
                "issue_date": "2018-03-02T15:19:08Z",
                "pushcount": 0,
                "security_sla": None,
                "respin_count": 0,
                "mailed": 0,
                "security_approved": None,
                "reporter_id": 3003255,
                "quality_responsibility_id": 139,
                "doc_complete": 0,
                "old_advisory": None,
                "product_id": 79,
                "filelist_changed": 0,
                "old_delete_product": None,
                "created_at": "2018-03-02T15:19:08Z",
                "text_only": False,
                "request": 0,
                "assigned_to_id": 3002255,
                "contract": None,
                "content_types": [],
                "release_date": None,
                "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
                "package_owner_id": 3002860,
                "fulladvisory": "RHBA-2018:32916-01",
                "published": 0,
                "filelist_locked": 0,
                "group_id": 436,
                "resolution": "",
                "embargo_undated": False
            }
        }
    },
    "who": {
        "user": {
            "preferences": {
                "default_filter_id": "1",
                "full_width_layout": "1",
                "color_scheme": "pink"
            },
            "user_organization_id": 142,
            "receives_mail": True,
            "enabled": 1,
            "login_name": "tbielawa@redhat.com",
            "orgchart_id": None,
            "email_address": None,
            "id": 3003255,
            "realname": "Tim Bielawa"
        }
    },
    "bugs": {
        "idsfixed": [],
        "bugs": [],
        "id_field": "id",
        "id_prefix": "bz:",
        "to_fetch": [],
        "type": "bugs",
        "errata": {
            "rhba": {
                "rating": 0,
                "rhnqa": 0,
                "state_machine_rule_set_id": None,
                "current_tps_run": None,
                "updated_at": "2018-03-07T20:47:23Z",
                "current_state_index_id": 204419,
                "is_brew": 1,
                "pushed": 0,
                "devel_responsibility_id": 3,
                "docs_responsibility_id": 1,
                "rhn_complete": 0,
                "rhnqa_shadow": 0,
                "actual_ship_date": None,
                "sign_requested": 0,
                "id": 32916,
                "update_date": "2018-03-02T15:19:08Z",
                "is_batch_blocker": False,
                "qa_complete": 0,
                "severity": "normal",
                "supports_multiple_product_destinations": True,
                "status_updated_at": "2018-03-02T15:19:08Z",
                "published_shadow": 0,
                "priority": "normal",
                "is_valid": 1,
                "manager_id": 3001032,
                "closed": 0,
                "batch_id": None,
                "security_impact": "None",
                "revision": 1,
                "status": "NEW_FILES",
                "publish_date_override": "2019-01-01T00:00:00Z",
                "text_ready": 0,
                "errata_id": 32916,
                "deleted": 0,
                "request_rcm_push_comment_id": None,
                "issue_date": "2018-03-02T15:19:08Z",
                "pushcount": 0,
                "security_sla": None,
                "respin_count": 0,
                "mailed": 0,
                "security_approved": None,
                "reporter_id": 3003255,
                "quality_responsibility_id": 139,
                "doc_complete": 0,
                "old_advisory": None,
                "product_id": 79,
                "filelist_changed": 0,
                "old_delete_product": None,
                "created_at": "2018-03-02T15:19:08Z",
                "text_only": False,
                "request": 0,
                "assigned_to_id": 3002255,
                "contract": None,
                "content_types": [],
                "release_date": None,
                "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
                "package_owner_id": 3002860,
                "fulladvisory": "RHBA-2018:32916-01",
                "published": 0,
                "filelist_locked": 0,
                "group_id": 436,
                "resolution": "",
                "embargo_undated": False
            }
        }
    },
    "content": {
        "content": {
            "revision_count": 1,
            "packages": None,
            "errata_id": 32916,
            "description": "Red Hat OpenShift Container Platform is the company's cloud computing Platform-as-a-Service (PaaS) solution designed for on-premise or private cloud deployments.\n\nThis advisory contains the RPM packages for Red Hat OpenShift Container Platform 3.5.z. See the following advisory for the container images for this release:\n\nhttps://access.redhat.com/errata/RHBA-2018:0114\n\nSpace precludes documenting all of the bug fixes and enhancements in this advisory. See the following Release Notes documentation, which will be updated shortly for this release, for details about these changes:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nAll OpenShift Container Platform 3.5 users are advised to upgrade to these updated packages and images.",
            "reference": "",
            "updated_at": "2018-03-02T15:19:08Z",
            "doc_review_due_at": None,
            "multilib": None,
            "solution": "Before applying this update, make sure all previously released errata relevant to your system have been applied.\n\nFor OpenShift Container Platform 3.5 see the following documentation, which will be updated shortly for release 3.5.z, for important instructions on how to upgrade your cluster and fully apply this asynchronous errata update:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nThis update is available via the Red Hat Network. Details on how to use the Red Hat Network to apply this update are available at https://access.redhat.com/articles/11258.",
            "how_to_test": None,
            "doc_reviewer_id": 1,
            "topic": "Red Hat OpenShift Container Platform releases 3.5.z are now available with updates to packages and images that fix several bugs and add enhancements.",
            "obsoletes": "",
            "keywords": "",
            "text_only_cpe": None,
            "product_version_text": None,
            "cve": "",
            "id": 30494,
            "crossref": ""
        }
    },
    "params": {
        "action": "show",
        "controller": "api/v1/erratum",
        "id": "32916",
        "format": "json"
    },
    "errata": {
        "rhba": {
            "rating": 0,
            "rhnqa": 0,
            "state_machine_rule_set_id": None,
            "current_tps_run": None,
            "updated_at": "2018-03-07T20:47:23Z",
            "current_state_index_id": 204419,
            "is_brew": 1,
            "pushed": 0,
            "devel_responsibility_id": 3,
            "docs_responsibility_id": 1,
            "rhn_complete": 0,
            "rhnqa_shadow": 0,
            "actual_ship_date": None,
            "sign_requested": 0,
            "id": 32916,
            "update_date": "2018-03-02T15:19:08Z",
            "is_batch_blocker": False,
            "qa_complete": 0,
            "severity": "normal",
            "supports_multiple_product_destinations": True,
            "status_updated_at": "2018-03-02T15:19:08Z",
            "published_shadow": 0,
            "priority": "normal",
            "is_valid": 1,
            "manager_id": 3001032,
            "closed": 0,
            "batch_id": None,
            "security_impact": "None",
            "revision": 1,
            "status": "NEW_FILES",
            "publish_date_override": "2019-01-01T00:00:00Z",
            "text_ready": 0,
            "errata_id": 32916,
            "deleted": 0,
            "request_rcm_push_comment_id": None,
            "issue_date": "2018-03-02T15:19:08Z",
            "pushcount": 0,
            "security_sla": None,
            "respin_count": 0,
            "mailed": 0,
            "security_approved": None,
            "reporter_id": 3003255,
            "quality_responsibility_id": 139,
            "doc_complete": 0,
            "old_advisory": None,
            "product_id": 79,
            "filelist_changed": 0,
            "old_delete_product": None,
            "created_at": "2018-03-02T15:19:08Z",
            "text_only": False,
            "request": 0,
            "assigned_to_id": 3002255,
            "contract": None,
            "content_types": [],
            "release_date": None,
            "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
            "package_owner_id": 3002860,
            "fulladvisory": "RHBA-2018:32916-01",
            "published": 0,
            "filelist_locked": 0,
            "group_id": 436,
            "resolution": "",
            "embargo_undated": False
        }
    }
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


######################################################################
# Primarily used by brew_test.py:

# This is a build object which is attached to an erratum that is open.
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


# This is a build object which is attached to an erratum and that
# erratum is still in an open state. "Open" as indicated by the errata
# object in "all_errata" with a status property of "NEW_FILES". See
# constants.errata_active_advisory_labels for a list of all status
# states considered 'open' (or 'active', or 'live').
image_build_attached_open_json = {
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
# END image_build_attached_open_json

# This is a build object which was attached to an erratum and that
# erratum has now shipped and is closed. "Shipped" as indicated by the
# errata object in "all_errata" with a status property of
# "SHIPPED_LIVE". See constants.errata_inactive_advisory_labels for a
# list of all status states considered 'closed'.
image_build_attached_closed_json = {
    "id": 660050,
    "nvr": "template-service-broker-docker-v3.7.36-2",
    "package": {
        "id": 40328,
        "name": "template-service-broker-docker"
    },
    "released_errata": None,
    "all_errata": [
        {
            "id": 90540,
            "name": "RHBA-2019:90540",
            "status": "SHIPPED_LIVE"
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
# END image_build_attached_closed_json

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

# Output as one would get from (as of 2018-04-02):
#
#     $ brew list-tagged rhaos-3.9-rhel-7-candidate --latest --type=image --quiet
#
# Used for mocking brew.get_tagged_image_builds()
brew_list_tagged_3_9_image_builds = """aos-f5-router-docker-v3.9.15-1            rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
aos3-installation-docker-v3.9.15-1        rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
atomic-openshift-descheduler-docker-v3.9.13-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
atomic-openshift-node-problem-detector-docker-v3.9.13-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
container-engine-docker-v3.9.15-1         rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
cri-o-docker-v3.9.15-1                    rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
golang-github-openshift-oauth-proxy-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
golang-github-openshift-prometheus-alert-buffer-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
golang-github-prometheus-alertmanager-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
golang-github-prometheus-node_exporter-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
golang-github-prometheus-prometheus-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
image-inspector-docker-v3.9.15-1          rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
jboss-datavirt-6-datavirt64-openshift-container-1.0-8  rhaos-3.9-rhel-7-candidate  jschatte
jenkins-slave-base-rhel7-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
jenkins-slave-maven-rhel7-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
jenkins-slave-nodejs-rhel7-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
logging-auth-proxy-docker-v3.9.15-1       rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
logging-curator-docker-v3.9.15-1          rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
logging-elasticsearch-docker-v3.9.15-1    rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
logging-eventrouter-docker-v3.9.15-1      rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
logging-fluentd-docker-v3.9.15-1          rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
logging-kibana-docker-v3.9.15-1           rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
metrics-cassandra-docker-v3.9.15-1        rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
metrics-hawkular-metrics-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
metrics-hawkular-openshift-agent-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
metrics-heapster-docker-v3.9.15-1         rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-apb-base-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-apb-tools-v3.9.1-1.4  rhaos-3.9-rhel-7-candidate  dzager
openshift-enterprise-asb-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-base-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-cluster-capacity-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-deployer-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-docker-builder-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-docker-v3.9.15-1     rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-dockerregistry-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-egress-router-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-federation-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-haproxy-router-docker-v3.9.14-8  rhaos-3.9-rhel-7-candidate  smunilla
openshift-enterprise-keepalived-ipfailover-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-mariadb-apb-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-mediawiki-apb-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-mediawiki-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-mysql-apb-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-node-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-openvswitch-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-pod-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-postgresql-apb-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-recycler-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-service-catalog-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-enterprise-sti-builder-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-jenkins-2-docker-v3.9.15-1      rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
openshift-local-storage-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
origin-web-console-server-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
ose-egress-http-proxy-docker-v3.9.15-1    rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
redhat-openjdk-18-openjdk18-openshift-container-1.3-5  rhaos-3.9-rhel-7-candidate  mgoldman
registry-console-docker-v3.9.15-1         rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
snapshot-controller-docker-v3.9.15-1      rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
snapshot-provisioner-docker-v3.9.15-1     rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com
template-service-broker-docker-v3.9.15-1  rhaos-3.9-rhel-7-candidate  ocp-build/buildvm.openshift.eng.bos.redhat.com"""


# Output as one would get from (as of 2018-04-02):
#
#     $ brew list-tagged rhaos-3.9-rhel-7-candidate --latest --rpm --quiet --arch src
#
# Used for mocking brew.get_tagged_rpm_builds()
#
# First example, 'ansible-asb-modules' has no '.src' suffix to ensure
# all parsing code branches are explored
brew_list_tagged_3_9_rpm_builds = """ansible-asb-modules-0.1.1-1.el7
ansible-kubernetes-modules-0.4.0-8.el7.src
ansible-service-broker-1.1.17-1.el7.src
apb-1.1.15-1.el7.src
apb-base-scripts-1.1.5-1.el7.src
atomic-openshift-3.9.15-1.git.0.3cffafd.el7.src
atomic-openshift-descheduler-3.9.13-1.git.267.bb59a3f.el7.src
atomic-openshift-dockerregistry-3.9.15-1.git.349.4cf0d1a.el7.src
atomic-openshift-node-problem-detector-3.9.13-1.git.167.5d6b0d4.el7.src
atomic-openshift-web-console-3.9.15-1.git.230.9dccb91.el7.src
cockpit-160-3.el7.src
containernetworking-plugins-0.5.2-5.el7.src
cri-o-1.9.10-1.git8723732.el7.src
cri-tools-1.0.0-2.alpha.0.git653cc8c.el7.src
dumb-init-1.1.3-12.el7.src
elastic-curator-3.5.0-2.el7.src
elasticsearch-2.4.4-1.el7.src
elasticsearch-cloud-kubernetes-2.4.4.01_redhat_1-1.el7.src
fluentd-0.12.42-1.el7.src
golang-github-openshift-oauth-proxy-2.1-2.git885c9f40.el7.src
golang-github-openshift-prometheus-alert-buffer-0-2.gitceca8c1.el7.src
golang-github-prometheus-alertmanager-0.14.0-1.git30af4d0.el7.src
golang-github-prometheus-node_exporter-3.9.15-1.git.887.ac540aa.el7.src
golang-github-prometheus-prometheus-2.1.0-1.git85f23d8.el7.src
golang-github-prometheus-promu-0-2.git85ceabc.el7.src
google-cloud-sdk-183.0.0-3.el7.src
haproxy-1.8.1-5.el7.src
hawkular-openshift-agent-1.2.2-2.el7.src
heapster-1.3.0-3.el7.src
http-parser-2.7.1-4.el7.src
image-inspector-2.1.2-2.el7.src
jenkins-1-1.651.2-2.el7.src
jenkins-2-plugins-3.9.1519779801-1.el7.src
jenkins-2.89.4.1519670652-1.el7.src
jenkins-plugin-ace-editor-1.1-10.el7.src
jenkins-plugin-authentication-tokens-1.3-1.el7.src
jenkins-plugin-blueocean-1.1.2-1.el7.src
jenkins-plugin-workflow-support-2.14-10.el7.src
kibana-4.6.4-4.el7.src
libuv-1.7.5-3.el7.src
mariadb-apb-role-1.1.10-1.el7.src
mediawiki-apb-role-1.1.7-1.el7.src
mediawiki-container-scripts-1.0.2-1.el7.src
mediawiki123-1.23.13-1.el7.src
mysql-apb-role-1.1.10-1.el7.src
nodejs-4.7.2-1.el7.src
nodejs-abbrev-1.0.7-1.el7aos.src
nodejs-accepts-1.3.3-1.el7.src
nodejs-align-text-0.1.3-2.el7aos.src
nodejs-yallist-2.0.0-2.el7.src
nodejs-yargs-3.24.0-1.el7aos.src
openshift-ansible-3.9.15-1.git.0.4858ebc.el7.src
openshift-elasticsearch-plugin-2.4.4.21__redhat_1-1.el7.src
openshift-enterprise-image-registry-3.8.0-1.git.216.b6b90bb.el7.src
openshift-eventrouter-0.1-2.git5bd9251.el7.src
openshift-external-storage-0.0.1-8.git78d6339.el7.src
openvswitch-ovn-kubernetes-0.1.0-2.el7.src
origin-kibana-4.5.1-8.el7.src
perl-IO-String-1.08-20.el7.src
postgresql-apb-role-1.1.14-1.el7.src
python-boto-2.34.0-5.el7.src
python-boto3-1.4.0-1.el7.src
python-botocore-1.4.57-5.el7.src
python-string_utils-0.6.0-2.el7.src
python-typing-3.5.2.2-3.el7.src
python-urllib3-1.21.1-1.el7.src
rubygem-activesupport-4.2.10-1.el7.src
rubygem-addressable-2.5.2-1.el7.src
rubygem-concurrent-ruby-1.0.5-1.el7.src
rubygem-cool.io-1.5.3-1.el7.src
rubygem-yajl-ruby-1.3.1-1.el7.src
runc-1.0.0-24.rc4.dev.gitc6e4a1e.el7.src
scons-2.5.1-1.el7.src
search-guard-2-2.4.4.10_redhat_1-3.el7.src
sshpass-1.06-2.el7.src
thrift-0.9.1-15.el7.src
v8-3.14.5.10-25.el7.src"""
