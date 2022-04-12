import re


class Bug:
    def __init__(self, bug_obj):
        self.bug = bug_obj

    @staticmethod
    def get_target_release(bugs) -> str:
        """
        Pass in a list of bugs and get their target release version back.
        Raises exception if they have different target release versions set.

        :param bugs: List[Bug] instance
        """
        invalid_bugs = []
        target_releases = set()

        if not bugs:
            raise ValueError("bugs should be a non empty list")

        for bug in bugs:
            # make sure it's a list with a valid str value
            valid_target_rel = isinstance(bug.target_release, list) and len(bug.target_release) > 0 and \
                re.match(r'(\d+.\d+.[0|z])', bug.target_release[0])
            if not valid_target_rel:
                invalid_bugs.append(bug)
            else:
                target_releases.add(bug.target_release[0])

        if invalid_bugs:
            err = 'target_release should be a list with a string matching regex (digit+.digit+.[0|z])'
            for b in invalid_bugs:
                err += f'\n bug: {b.id}, target_release: {b.target_release} '
            raise ValueError(err)

        if len(target_releases) != 1:
            err = f'Found different target_release values for bugs: {target_releases}. ' \
                'There should be only 1 target release for all bugs. Fix the offending bug(s) and try again.'
            raise ValueError(err)

        return target_releases.pop()


class BugTracker:
    def __init__(self, config):
        self.config = config
        self._server = config.get('server')

    def target_release(self):
        return self.config.get('target_release')

    def search(self):
        raise NotImplementedError

    def blocker_search(self):
        raise NotImplementedError
