import os
import re

from punic import shshutil as shutil
from punic.config import config
from punic.logger import logger
from punic.runner import runner
from punic.xcode import XcodeProject


class Checkout(object):
    def __init__(self, punic, identifier, revision):
        self.punic = punic
        self.identifier = identifier
        self.repository = self.punic._repository_for_identifier(self.identifier)
        self.revision = revision
        self.checkout_path = self.config.checkouts_path / self.identifier.project_name

    @property
    def config(self):
        return self.punic.config

    def prepare(self):

        if self.config.use_submodules:
            relative_checkout_path = self.checkout_path.relative_to(self.config.root_path)

            result = runner.run('git submodule status "{}"'.format(relative_checkout_path))
            if result.return_code == 0:
                match = re.match(r'^(?P<flag> |\-|\+|U)(?P<sha>[a-f0-9]+) (?P<path>.+) \((?P<description>.+)\)', result.stdout)
                flag = match.groupdict()['flag']
                if flag == ' ':
                    pass
                elif flag == '-':
                    raise Exception('Uninitialized submodule P{. Please report this!'.format(self.checkout_path))
                elif flag == '+':
                    raise Exception('Submodule {} doesn\'t match expected revision'.format(self.checkout_path))
                elif flag == 'U':
                    raise Exception('Submodule {} has merge conflicts'.format(self.checkout_path))
            else:
                if self.checkout_path.exists():
                    raise Exception('Want to create a submodule in {} but something already exists in there.'.format(self.checkout_path))
                logger.debug('Adding submodule for {}'.format(self))
                runner.check_run(['git', 'submodule', 'add', '--force', self.identifier.remote_url, self.checkout_path.relative_to(self.config.root_path)])

            # runner.check_run(['git', 'submodule', 'add', '--force', self.identifier.remote_url, self.checkout_path.relative_to(self.config.root_path)])
            # runner.check_run(['git', 'submodule', 'update', self.checkout_path.relative_to(self.config.root_path)])

            logger.debug('Updating {}'.format(self))
            self.repository.checkout(self.revision)
        else:

            # TODO: This isn't really 'fetch'
            if self.config.fetch:

                self.repository.checkout(self.revision)
                logger.debug('<sub>Copying project to <ref>Carthage/Checkouts</ref></sub>')
                if self.checkout_path.exists():
                    shutil.rmtree(self.checkout_path)
                shutil.copytree(self.repository.path, self.checkout_path, ignore=shutil.ignore_patterns('.git'))

        if not self.checkout_path.exists():
            raise Exception('No checkout at path: {}'.format(self.checkout_path))

        # We only need to bother making a symlink to <root>/Carthage/Build if dependency also has dependencies.
        if len(self.punic.dependencies_for_project_and_tag(self.identifier, self.revision)):
            # Make a Carthage/Build symlink inside checked out project.
            carthage_path = self.checkout_path / 'Carthage'
            if not carthage_path.exists():
                carthage_path.mkdir()

            carthage_symlink_path = carthage_path / 'Build'
            if carthage_symlink_path.exists():
                carthage_symlink_path.unlink()
            logger.debug('<sub>Creating symlink: <ref>{}</ref> to <ref>{}</ref></sub>'.format(carthage_symlink_path.relative_to(self.config.root_path), self.config.build_path.relative_to(self.config.root_path)))
            assert self.config.build_path.exists()
            os.symlink(str(self.config.build_path), str(carthage_symlink_path))

    @property
    def projects(self):
        def _make_cache_identifier(project_path):
            rev = self.repository.rev_parse(self.revision)
            cache_identifier = '{},{}'.format(str(rev), project_path.relative_to(self.checkout_path))
            return cache_identifier

        project_paths = self.checkout_path.glob("*.xcodeproj")
        projects = [XcodeProject(self, config.xcode, project_path, _make_cache_identifier(project_path)) for project_path in project_paths]
        return projects