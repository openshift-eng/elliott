# Cutting a New OCP Branch

### Setup DistGits
- A ticket must be created with RCM to ask them to create new `3.<X+1>` branches and tags in their system. Ideally this should be requested a couple weeks before it's needed. For example: https://projects.engineering.redhat.com/browse/RCM-34112
- Run `./oit.py --working-dir ../workspace/ --group openshift-3.<X> images:merge-branch --target private-3.<X+1> --allow-overwrite --no-push`
    - This will automatically move all old commits from the previous version branch to the new, retaining all history. After running with `--no-push` as above with no errors, change to `--push` and rerun.

### Create Configs
- Copy `./groups/openshift-3.<X>` to `./groups/openshift-3.<X+1>`
- Open `./groups/openshift-3.<X+1>/group.yml`
    - Increment `vars.MINOR` at top of file

### Setup Jenkins Jobs

The jenkins jobs have their own process doc here: https://github.com/openshift/aos-cd-jobs/blob/master/docs/sop/cut-new-release.md
Follow those instructions to complete the update.