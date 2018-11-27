# Elliott - Errata Tool Automation

*Elliott* is a tool for automating several aspects of the errata
lifecycle. This exists because the Errata/Advisory process has hooks
into several other systems, and coordinating all of that manually is
tedious and error prone.


# Table of Contents

   * [Basics &amp; Terminology](#basics--terminology)
   * [Setup and Installation](#setup-and-installation)
      * [Additional Softwares](#additional-softwares)
      * [Authenticating](#authenticating)
   * [Tests](#tests)
   * [Usage](#usage)
      * [`advisory:get` - Viewing an Advisory](#advisoryget---viewing-an-advisory)
      * [`advisory:create` - Create a New Advisory](#advisorycreate---create-a-new-advisory)
      * [`advisory:change-state` - Change the State of an Advisory](#advisorychange-state---change-the-state-of-an-advisory)
      * [`advisory:find-bugs` - Find Bugzilla Bugs, Add to an Advisory](#advisoryfind-bugs---find-bugzilla-bugs-add-to-an-advisory)
      * [`advisory:find-builds` - Find Brew RPM/Image Builds, Add to an Advisory](#advisoryfind-builds---find-brew-rpmimage-builds-add-to-an-advisory)



# Basics & Terminology

To operate Elliott with any skill it is beneficial to first understand
the language we use, as well as the errata process a little bit. Let's
cover some basics.

* Elliott is this software, write it capital or lower-case E, either
  way is fine as long as you remember that it ends with **two** "t"s
* Elliott was first created by
  [Sam Munilla](https://www.cdc.gov/salmonella/index.html) and is a
  reference to Steven Spielberg's 1982 summer blockbuster,
  [E.T. the Extra-Terrestrial](http://www.imdb.com/title/tt0083866/)
  * "ET" is also a short-hand way of referencing the [Errata Tool](https://errata.devel.redhat.com/), see the connection now?
* Grammar and Synonyms
  * **Erratum** - is the *singluar* version of the word "Errata"
  * **Errata** - is *plural*, and it refers to a collection of "Erratum"
  * **Advisory** - is another word we use and it is interchangable for
  Errata and Erratum
    * This word is mostly used by humans in conversation, or in print
      as an informational message ("this bug has been attached to
      advisory RHBA-1337")
	* Behind the scenes, APIs and code generally use the term erratum
* Brew Builds - NVRs (*Name-Version-Release*) and Numeric IDs
  * Use an NVR or a numeric build ID interchangeably in subcommands
  * For example, `apb-1.1.16-1.el7` is an NVR for the build
    [668623](https://brewweb.engineering.redhat.com/brew/buildinfo?buildID=668623)
  * This is the `apb` package, version `1.1.16`, first release (`-1`),
    for RHEL 7 (`.el7`)


The Errata Tool is the central record keeping location when software
is first released or updated. An advisory is created for every new
release or update in a product series. Advisory contain references to
items in several other public and private systems.

* Bugzilla bugs are added to advisory, their status (`VERIFIED`,
  `ON_QA`, etc) is refreshed periodically as an advisory can not move
  forward for release until all associated bugs have passed testing
* Brew RPM builds are attached to advisory, these contain the latest
software and bug fixes
* When the RPM builds are signed, brew image (container) builds are
  created using the new/updated RPMs and are attached to a separate
  advisory

# Setup and Installation

## Additional Softwares

Elliott requires additional command line tools to fully function:

1. `brew` - Installation instructions are
   [available in Mojo](https://mojo.redhat.com/docs/DOC-1071519). Requires
   an active kerberos ticket to use.
1. `bugzilla` - Available through DNF repos as the
   `python-bugzilla-cli` package. **Ensure** that you run `bugzilla
   login` after installation!


## Authenticating

Ensure you have a valid kerberos ticket before proceeding. A valid
kerberos ticket is required to use elliott. See the following link for
assistance with the basics of kerberos at Red Hat:

* [DOC-87898](https://mojo.redhat.com/docs/DOC-87898) - Mojo - Using Kerberos Authentication

Once you have that taken care of you should run a simple command from
elliott. I suggest the following, it will verify that you can access
the Errata Tool successfully by attempting to get a list of recently
created advisory:

    <enterprise-images> $ ./tools/src/elliott.py advisory:list
    2018-03-02T15:19:08 NEW_FILES TEST OpenShift Container Platform 3.5 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32916
    2018-01-25T19:19:15 NEW_FILES OpenShift Container Platform 3.3 and 3.4 images update https://errata.devel.redhat.com/advisory/32352
    2018-01-25T19:15:25 NEW_FILES OpenShift Container Platform 3.3 and 3.4 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32351
    2018-01-24T15:01:59 NEW_FILES OpenShift Container Platform 3.7, 3.6, 3.5 images update https://errata.devel.redhat.com/advisory/32337
    2018-01-24T14:56:43 NEW_FILES OpenShift Container Platform 3.7, 3.6, and 3.5 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32336

# Tests

I usually run the unittests with this setup:

* Switch into the `tools` directory if you aren't already
* Run `. ./hack/env_setup.sh`
* Switch back to the repository root directory

Then run the unit tests:

    $ nosetests -v --with-cover --cover-package=ocp_cd_tools --cover-html \
        src/ocp_cd_tools/brew_test.py \
        src/ocp_cd_tools/errata_test.py \
        src/ocp_cd_tools/bugzilla_test.py

Add or remove any other `*_test.py` tests you wish.

If that works then you can open the HTML coverage report:

* `xdg-open cover/index.html`


# Usage

Here we describe how to effectively use elliott.

**NOTE:** Every elliott `advisory:<foo>` command has a thoroughly
detailed `--help` page. This includes examples and descriptions of all
options. We will not be listing each and every single option for every
command here. This will focus on getting you comfortable with the
basics.

## `advisory:get` - Viewing an Advisory

You have [already seen](#authenticating) how to list recently created
errata with `advisory:list`, now let's look at a single one in more
detail using the `advisory:get` command.

To get started, copy one of the IDs returned from the `advisory:list`
command, for example `32916`, one of our test advisories from the
previous example. We'll pass that directly to `advisory:get`. You will
see the same brief output as you did before.

    <enterprise-images> $ ./tools/src/elliott.py advisory:get 32916
    2018-03-02T15:19:08 NEW_FILES TEST OpenShift Container Platform 3.5 bug fix and enhancement update https://errata.devel.redhat.com/advisory/32916

Say you want additional information about this specific advisory. In
which case you can give the `--json` option to the command (this is
all documented in the commands `--help` output as well):

    <enterprise-images> $ ./tools/src/elliott.py advisory:get 32916 --json
    {
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
    	  ...

The returned JSON object is quite large and sprawling. I recommend
piping it into the `jq` tool if you want to trim down the
output. Piping it into a pager afterwards is also nice if you want to
scroll through it. For example, to look at just the `content` (basic
information) returned from the API you could use the `.content` filter
in `jq`:

    $ ./tools/src/elliott.py advisory:get 32916 --json | jq '.content' | less
    {
      "content": {
        "revision_count": 1,
        "packages": null,
        "errata_id": 32916,
        "description": "Red Hat OpenShift Container Platform is the company's cloud ...

## `advisory:create` - Create a New Advisory

Creating an advisory with elliott requires very little input as far as
errata details are concerned. You MUST provide:

* The product release (`openshift-3.Y`)

A release date is automatically selected for you. However, you MAY
override this date if there is a problem with it. The kind of advisory
this is must be specified. Valid choices include `rpm` and `image`.

**NOTE:** This command will **NOT** create an advisory without your
explicit instructions.

Here are two examples from the `--help` option:

Preview an RPM Advisory 21 days from now (the default release date)
for OSE 3.9. The default boilerplate text will be printed to the
screen in the form of the JSON object that *would* have been submitted
to the API:

    <enterprise-images> $ ./tools/src/elliott.py --group openshift-3.9 advisory:create --kind rpm

Create an Image Advisory for the 3.5 series on the first Monday in
March. The date is given in simple `YYYY-MM-DD` format, and finally we
give explicit confirmation to create the advisory by providing the
`--yes` option:

    <enterprise-images> $ ./tools/src/elliott.py --group openshift-3.5 advisory:create \
        --kind image \
        --date 2018-03-05 \
        --yes

## `advisory:change-state` - Change the State of an Advisory

Change the state of an advisory. For example, move an advisory from
`NEW_FILES` where bugs and builds are still being added, to `QE`
state where the testers are able to take over.

Here we'll move our example test advisory 32916 from `NEW_FILES` to
`QE`:

    <enterprise-images> $ ./tools/src/elliott.py advisory:change-state --state QE 32916

## `advisory:find-bugs` - Find Bugzilla Bugs, Add to an Advisory

Bugzilla bugs can be attached automatically to an advisory. This keeps
track of which documented issues/enhancements are included in an
advisory when it ships. Additionally, it is important to know that an
advisory can not change to the QE state until attached bugs have been
verified to a certain degree. The Errata Tool UI will show this
information to you in the form of percentages indicating how many
attached bugs are in each state.

Bugzilla queries are constructed for a given product release (ex:
openshift-3.9) to return bugs which are in a `MODIFIED` state. In
Bugzilla, this `MODIFIED` state indicates that the engineer has
written code to implement the enhancement or fix the specific bug and
the associated code has been merged into that components git
repository.

Technically speaking, candidate bugs are bugs in the `MODIFIED` state
which have a `TARGET RELEASE` set to the supplied product version (GA
or ASYNC update).

`advisory:find-bugs` has two modes of operation:

1. Query Bugzilla automatically and attach all discovered bugs (as
   described above)
1. Provide bug IDs manually on the command line

Example: Automatically *find* bugs for an OpenShift 3.9 update (but do
not attach them). Notice how we do not need to provide an advisory:

	<enterprise-images> $ ./tools/src/elliott.py --group openshift-3.9 advisory:find-bugs --auto
	2018-03-19T17:49:44.573042 Searching group directory: /home/tbielawa/rhat/cd/enterprise-images/groups/openshift-3.9
	2018-03-19T17:49:44.584135 Using branch from group.yml: rhaos-3.9-rhel-7
	Would have added 7 bugs: 1537593, 1510212, 1519365, 1529482, 1550797, 1543647, 1551904

In order to add bugs to an advisory you must provide the ID of an
advisory as the value to the `--add` option:

    <enterprise-images> $ ./tools/src/elliott.py --group openshift-3.9 advisory:find-bugs --auto --add 32916

Flags may be added to the identified bugs by using the `--flag`
option.

Provide one or more bugs manually by using the `--id` option.

See the `--help` output for additional examples and descriptions.


## `advisory:find-builds` - Find Brew RPM/Image Builds, Add to an Advisory

Brew RPM and Image builds can be attached to advisory. As we noted
already in the `advisory:create` command, we deal with two different
types of advisory, RPM and Image. When you're attaching builds ensure
you are attaching the right build to the matching advisory.

A build must meet very specific criteria to be considered as a viable
build to add to an advisory. For example, assuming
`--group=openshift-3.7`, then a build is a VIABLE BUILD *IFF* it meets
ALL of the following criteria:

  * HAS the tag in brew: `rhaos-3.7-rhel7-candidate`
  * DOES NOT have the tag in brew: `rhaos-3.7-rhel7`
  * IS NOT attached to any *OPEN* RHBA, RHSA, or RHEA

That is to say, a viable build is tagged as a "candidate", has NOT
received the "shipped" tag yet, and is NOT attached to any *OPEN*
advisory (closed advisory are allowed).

Here is an example of how we could look up image builds that would be
attached to a 3.6 advisory:

    <enterprise-images> $ ./tools/src/elliott.py --group openshift-3.6 advisory:find-builds -k image
    2018-03-20T13:57:45.244036 Searching group directory: /home/tbielawa/rhat/cd/enterprise-images/groups/openshift-3.6
    2018-03-20T13:57:45.253068 Using branch from group.yml: rhaos-3.6-rhel-7
    Searching Brew for build candidates: Hold on a moment
	Refreshing for tag: rhaos-3.6-rhel-7
	Refreshing for tag: rhaos-3.6-rhel-7-candidate
    The following 67 builds may be attached to an advisory:
     {'file_types': ['tar'], 'product_version': 'RHEL-7-OSE-3.6', 'build': 'aos-f5-router-docker-v3.6.173.0.110-1'}
     {'file_types': ['tar'], 'product_version': 'RHEL-7-OSE-3.6', 'build': 'aos3-installation-docker-v3.6.173.0.110-1'}
     {'file_types': ['tar'], 'product_version': 'RHEL-7-OSE-3.6', 'build': 'container-engine-docker-v3.6.173.0.110-1'}
     ...

If we ran that same command again and suppplied the `--attach` option
with a valid `ADVISORY` number as the argument then the discovered
builds would be attached to the advisory instead of just printed to
the screen.

We may also provide build NVRs or numeric build IDs manually with the
`--build` (`-b`) option. As with automatic discovery, a `--kind
{rpm,image}` option must still be supplied.

See the `--help` output for additional examples and descriptions.
