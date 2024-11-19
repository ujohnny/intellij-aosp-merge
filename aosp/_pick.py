import argparse
import subprocess
import sys

from ._git import git_setup_intellij, git_rebase_in_progress, git_log, git_read_aosp_commit
from ._patch import execute as patch, configure as patch_configure
from ._test import execute as test, configure as test_configure
from ._consts import INTELLIJ_REF, AOSP_URL
from ._util import log, log_error, choose, ask


def git_get_head(repo: str) -> str:
    """
    Gets the hash of the git HEAD.
    """

    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo,
    ).decode().strip()


def git_branch(repo: str, src: str, name: str):
    """
    Branches from a specific branch and checks it out.
    """

    # first try deleting the branch in the case it already exists
    subprocess.call(
        ['git', 'branch', '-D', name],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )

    subprocess.check_call(
        ['git', 'branch', name, src],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ['git', 'checkout', name, '-f'],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def git_cherry_pick(repo: str, commit: str) -> bool:
    """
    Runs a git cherry-pick.
    """

    result = subprocess.run(
        ['git', 'cherry-pick', commit],
        cwd=repo,
        stderr=sys.stdout,
        stdout=sys.stdout,
    )

    return result.returncode == 0


def git_cherry_pick_continue(repo: str):
    subprocess.check_call(
        ['git', 'cherry-pick', '--continue'],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def git_cherry_pick_abort(repo: str):
    subprocess.check_call(
        ['git', 'cherry-pick', '--abort'],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def git_push(repo: str, branch: str):
    subprocess.check_call(
        ['git', 'push',  '--set-upstream', 'origin', branch, '-f'],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def git_checkout_reset(repo: str):
    """
    Returns to the previously checkedout branch.
    """

    subprocess.call(
        ['git', 'checkout',  '-', '-f'],
        cwd=repo,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def try_pick(repo: str, commit: str):
    """
    Tries to cherry-pick the commit.
    """

    success = git_cherry_pick(repo, commit)

    if success:
        log('commit picked')
        return

    # if the pick failed but a rebase is in progress, there are conflicts
    if not git_rebase_in_progress(repo):
        log_error('pick failed')

    result = choose(
        title='could not resolve conflicts automaticaly',
        options=[
            '[c] resolved conflicts, continue',
            '[a] abort',
        ],
    )

    if result == 'a':
        git_cherry_pick_abort(repo)
        git_checkout_reset(repo)
        sys.exit(0)

    git_cherry_pick_continue(repo)
    log('commit picked')


def create_pr(repo: str, aosp_commit: str, draft: bool):
    """
    Uses the github cli to create a new PR.
    """

    title = '[AOSP-pick] %s' % git_log(repo, aosp_commit, '%s')
    body = 'Cherry pick AOSP commit [%s](%s%s).\n\n%s' % (
        aosp_commit,
        AOSP_URL,
        aosp_commit,
        git_log(repo, aosp_commit, '%b'),
    )

    subprocess.check_call(
        [
            'gh',
            'pr',
            'create',
            '--repo',
            'bazelbuild/intellij',
            '--title',
            title,
            '--body',
            body,
            '--reviewer',
            'LeFrosch',
        ] + (['--draft'] if draft else []),
        cwd=repo,
        stderr=sys.stdout,
        stdout=sys.stdout,
    )


def configure(parser: argparse.ArgumentParser):
    patch_configure(parser)
    test_configure(parser)

    parser.add_argument(
        '--notest',
        action='store_true',
        help='run tests automatically',
        default=False,
    )
    parser.add_argument(
        '--draft',
        action='store_true',
        help='creates a draft PR',
        default=False,
    )


def execute(args: argparse.Namespace):
    if not patch(args):
        return

    if not args.notest:
        test(args)

    if not ask('create PR from commit'):
        return

    repo = args.repo
    git_setup_intellij(repo)

    commit = git_get_head(repo)
    aosp_commit = git_read_aosp_commit(repo, commit)

    log('creating PR for aosp commit %s' % aosp_commit)

    branch = 'AOSP/%s' % aosp_commit
    git_branch(repo, INTELLIJ_REF, branch)
    log('checkout PR branch')

    try:
        try_pick(repo, commit)

        git_push(repo, branch)
        log('branch pushed')

        create_pr(repo, aosp_commit, args.draft)
        log('PR created')

    finally:
        git_checkout_reset(repo)
