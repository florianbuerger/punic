from __future__ import division, absolute_import, print_function

__version__ = '0.1.13'
__all__ = ['Punic']

import os
from copy import copy
from pathlib2 import Path
from .cartfile import Cartfile
from .checkout import Checkout
from .config import config
from .logger import logger
from .repository import Repository, Revision
from .resolver import Resolver, Node
from .runner import runner
from .specification import ProjectIdentifier, Specification, VersionPredicate, VersionOperator
from .xcode import XcodeBuildArguments
import punic.shshutil as shutil

class Punic(object):
    __slots__ = ['root_path', 'config', 'all_repositories', 'root_project']

    def __init__(self, root_path=None):

        if not root_path:
            root_path = Path.cwd()

        self.config = config

        root_project_identifier = ProjectIdentifier(overrides=None, project_name=self.config.root_path.name)

        self.all_repositories = {root_project_identifier: Repository(punic=self, identifier=root_project_identifier, repo_path=self.config.root_path),}

        self.root_project = self._repository_for_identifier(root_project_identifier)

    def _resolver(self):
        return Resolver(root=Node(self.root_project.identifier, None), dependencies_for_node=self._dependencies_for_node)

    def _dependencies_for_node(self, node):
        assert not node.version or isinstance(node.version, Revision)
        dependencies = self.dependencies_for_project_and_tag(identifier=node.identifier, tag=node.version)
        return dependencies

    def resolve(self):
        # type: (bool)
        resolver = self._resolver()
        build_order = resolver.resolve_build_order()

        for index, value in enumerate(build_order[:-1]):
            dependency, version = value
            logger.debug('{} <ref>{}</ref> <rev>{}</rev> <ref>{}</ref>'.format(index + 1, dependency, version.revision if version else '', dependency.remote_url))

        specifications = [Specification(identifier=dependency, predicate=VersionPredicate('"{}"'.format(version.revision))) for dependency, version in build_order[:-1]]
        logger.debug("<sub>Saving</sub> <ref>Cartfile.resolved</ref>")

        cartfile = Cartfile(use_ssh=self.config.use_ssh, specifications=specifications)
        cartfile.write((self.config.root_path / 'Cartfile.resolved').open('w'))

    def graph(self):
        # type: (bool) -> DiGraph
        return self._resolver().resolve()

    # TODO: This can be deprecated and the fetch flag relied on instead
    def fetch(self, dependencies=None):

        configuration, platforms = self.config.configuration, self.config.platforms

        if not self.config.build_path.exists():
            self.config.build_path.mkdir(parents=True)

        self._ordered_dependencies(name_filter=dependencies)

    def build(self, dependencies):
        # type: ([str])

        logger.info('Using xcode version: {}'.format(self.config.xcode))

        configuration, platforms = self.config.configuration, self.config.platforms

        if not self.config.build_path.exists():
            self.config.build_path.mkdir(parents=True)

        filtered_dependencies = self._ordered_dependencies(name_filter=dependencies)

        checkouts = [Checkout(punic=self, identifier=identifier, revision=revision) for identifier, revision in filtered_dependencies]


        skips = self.config.skips

        def filter_dependency(platform, checkout, project, scheme):
            platform = platform.name
            checkout = checkout.identifier.project_name
            project = project.path.name
            scheme = scheme.name

            for skip in skips:
                current = [ platform, checkout, project, scheme ][:len(skip)]
                if skip == current:
                    # print(skip)
                    # print(current)
                    # print('SKIP?')
                    return False
            return True


        for platform in platforms:
            for checkout in checkouts:
                checkout.prepare()
                for project in checkout.projects:
                    schemes = project.schemes

                    schemes = [scheme for scheme in schemes if scheme.framework_target]
                    schemes = [scheme for scheme in schemes if platform.device_sdk in scheme.framework_target.supported_platform_names]
                    for scheme in schemes:
                        if not filter_dependency(platform, checkout, project, scheme):
                            logger.warn('<sub>Skipping</sub>: {} / {} / {} / {}'.format(platform, checkout.identifier.project_name, project.path.name, scheme.name))
                            continue
                        self._build_one(platform, project, scheme.name, configuration)

    def _ordered_dependencies(self, name_filter=None):
        # type: (bool, [str]) -> [(ProjectIdentifier, Revision)]

        cartfile = Cartfile(use_ssh=self.config.use_ssh, overrides=config.repo_overrides)
        cartfile.read(self.config.root_path / 'Cartfile.resolved')

        def _predicate_to_revision(spec):
            repository = self._repository_for_identifier(spec.identifier)
            if spec.predicate.operator == VersionOperator.commitish:
                return Revision(repository=repository, revision=spec.predicate.value, revision_type=Revision.Type.commitish)
            else:
                raise Exception("Cannot convert spec to revision: {}".format(spec))

        dependencies = [(spec.identifier, _predicate_to_revision(spec)) for spec in cartfile.specifications]
        resolved_dependencies = self._resolver().resolve_versions(dependencies)
        resolved_dependencies = [dependency for dependency in resolved_dependencies if dependency[0].matches(name_filter)]
        return resolved_dependencies

    def _repository_for_identifier(self, identifier):
        # type: (ProjectIdentifier) -> Repository
        if identifier in self.all_repositories:
            return self.all_repositories[identifier]
        else:
            repository = Repository(self, identifier=identifier)
            if self.config.fetch:
                repository.fetch()
            self.all_repositories[identifier] = repository
            return repository

    def dependencies_for_project_and_tag(self, identifier, tag):
        # type: (ProjectIdentifier, Revision) -> [ProjectIdentifier, [Revision]]

        assert isinstance(identifier, ProjectIdentifier)
        assert not tag or isinstance(tag, Revision)

        repository = self._repository_for_identifier(identifier)
        specifications = repository.specifications_for_revision(tag)

        def make(specification):
            repository = self._repository_for_identifier(specification.identifier)
            tags = repository.revisions_for_predicate(specification.predicate)
            if specification.predicate.operator == VersionOperator.commitish:
                tags.append(Revision(repository=repository, revision=specification.predicate.value, revision_type=Revision.Type.commitish))
                tags.sort()
            assert len(tags)
            return repository.identifier, tags

        return [make(specification) for specification in specifications]

    def _build_one(self, platform, project, scheme, configuration):

        if self.config.dry_run:
            for sdk in platform.sdks:
                logger.warn('<sub>DRY-RUN: (Not) Building</sub>: <ref>{}</ref> (scheme: {}, sdk: {}, configuration: {})...'.format(project.path.name, scheme, sdk, configuration))
            return

        products = dict()

        toolchain = self.config.toolchain

        # Build device & simulator (if sim exists)
        for sdk in platform.sdks:
            logger.info('<sub>Building</sub>: <ref>{}</ref> (scheme: {}, sdk: {}, configuration: {})...'.format(project.path.name, scheme, sdk, configuration))

            derived_data_path = self.config.derived_data_path

            arguments = XcodeBuildArguments(scheme=scheme, configuration=configuration, sdk=sdk, toolchain=toolchain, derived_data_path=derived_data_path)

            product = project.build(arguments=arguments)
            products[sdk] = product

        self._post_process(platform, products)

    def _post_process(self, platform, products):

        ########################################################################################################

        logger.debug("<sub>Post processing</sub>...")

        # By convention sdk[0] is always the device sdk (e.g. 'iphoneos' and not 'iphonesimulator')
        device_sdk = platform.device_sdk
        device_product = products[device_sdk]

        ########################################################################################################

        output_product = copy(device_product)
        output_product.target_build_dir = self.config.build_path / platform.output_directory_name

        ########################################################################################################

        logger.debug('<sub>Copying binary</sub>...')
        if output_product.product_path.exists():
            shutil.rmtree(output_product.product_path)
        shutil.copytree(device_product.product_path, output_product.product_path)

        ########################################################################################################

        if len(products) > 1:
            logger.debug('<sub>Lipo-ing</sub>...')
            executable_paths = [product.executable_path for product in products.values()]
            command = ['/usr/bin/xcrun', 'lipo', '-create'] + executable_paths + ['-output', output_product.executable_path]
            runner.check_run(command)
            mtime = executable_paths[0].stat().st_mtime
            os.utime(str(output_product.executable_path), (mtime, mtime))

        ########################################################################################################

        logger.debug('<sub>Copying swiftmodule files</sub>...')
        for product in products.values():
            for path in product.module_paths:
                relative_path = path.relative_to(product.product_path)
                shutil.copyfile(path, output_product.product_path / relative_path)

        ########################################################################################################

        logger.debug('<sub>Copying bcsymbolmap files</sub>...')
        for product in products.values():
            for path in product.bcsymbolmap_paths:
                shutil.copy(path, output_product.target_build_dir)

        ########################################################################################################

        logger.debug('<sub>Producing dSYM files</sub>...')
        command = ['/usr/bin/xcrun', 'dsymutil', str(output_product.executable_path), '-o', str(output_product.target_build_dir / (output_product.executable_name + '.dSYM'))]
        runner.check_run(command)

        ########################################################################################################