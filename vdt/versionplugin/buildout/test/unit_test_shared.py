from mock import call, Mock, MagicMock, sentinel
import pytest
import os

from vdt.versionplugin.buildout.shared import delete_old_packages
from vdt.versionplugin.buildout.shared import build_dependent_packages
from vdt.versionplugin.buildout.shared import fpm_command
from vdt.versionplugin.buildout.shared import read_dependencies_setup_py
from vdt.versionplugin.buildout.shared import extend_extra_args
from vdt.versionplugin.buildout.shared import lookup_versions
from vdt.versionplugin.buildout.shared import parse_version_extra_args
from vdt.versionplugin.buildout.shared import traverse_dependencies
from vdt.versionplugin.buildout.shared import strip_dependencies
from vdt.versionplugin.buildout.shared import download_package
from vdt.versionplugin.buildout.shared import build_with_fpm
from vdt.versionplugin.buildout.shared import ruby_to_json
from vdt.versionplugin.buildout.shared import read_dependencies_package
from vdt.versionplugin.buildout.shared import parse_from_dpkg_output


@pytest.fixture
def mock_logger(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.log', Mock())


def test_delete_old_packages(monkeypatch, mock_logger):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.glob.glob',
                        Mock(return_value=['test-1.deb', 'test-2.deb', 'test-3.deb']))
    mock_os = Mock()
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.remove', mock_os)

    delete_old_packages()

    mock_os.assert_has_calls([call('test-1.deb'), call('test-2.deb'), call('test-3.deb')])


def test_traverse_dependencies(monkeypatch):
    mock_build_dependent_packages = Mock(side_effect=[{'test3': '2.0.0', 'test4': '2.0.0'},
                                                      {'test5': '3.0.0', 'test6': None},
                                                      None])
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.build_dependent_packages',
                        mock_build_dependent_packages)

    traverse_dependencies({'test1': '1.0.0', 'test2': '1.0.0'}, 'versions.cfg')

    mock_build_dependent_packages.assert_has_calls([call({'test1': '1.0.0', 'test2': '1.0.0'},
                                                         'versions.cfg'),
                                                    call({'test3': '2.0.0', 'test4': '2.0.0'},
                                                         'versions.cfg'),
                                                    call({'test5': '3.0.0', 'test6': None},
                                                         'versions.cfg')])


def test_strip_dependencies():
    setup_mock = Mock()
    setup_mock.call_args = [None, {'install_requires': ['test1==1.0.0', 'Test2<=2.0.0',
                                                        'test3>=3.0.0', 'Test4!=4.0.0', 'Test5']}]

    dependencies = strip_dependencies(setup_mock)

    assert dependencies == ['test1', 'test2', 'test3', 'test4', 'test5']


def test_strip_dependencies_exception():
    setup_mock = Mock(side_effect=Exception('Boom!'))

    dependencies = strip_dependencies(setup_mock)

    assert len(dependencies) == 0


def test_build_with_fpm(monkeypatch, mock_logger):
    mock_fpm_command = Mock(return_value='fpm -s python -t deb')
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.fpm_command',
                        mock_fpm_command)
    mock_subprocess_check_output = Mock()
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.subprocess.check_output',
                        mock_subprocess_check_output)

    build_with_fpm('puka', 'setup.py', extra_args=['-d', 'python-fabric >= 1.0.0',
                                                   '-d', 'python-setuptools >= 2.0.0'])

    mock_fpm_command.assert_called_with('puka', 'setup.py',
                                        extra_args=['-d', 'python-fabric >= 1.0.0',
                                                    '-d', 'python-setuptools >= 2.0.0'],
                                        no_python_dependencies=True,
                                        version=None)

    mock_subprocess_check_output.assert_called_with('fpm -s python -t deb')


def test_build_dependent_packages(monkeypatch, mock_logger):
    mock_build_with_fpm = Mock()
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.build_with_fpm', mock_build_with_fpm)
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.ruby_to_json', MagicMock())
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.read_dependencies_package',
                        Mock(side_effect=[['fabric', 'setuptools'],
                                          ['paramiko', 'requests'],
                                          None]))
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.lookup_versions',
                        Mock(side_effect=[{'fabric': '1.0.0', 'setuptools': '2.0.0'},
                                          {'paramiko': '3.0.0', 'requests': None}]))

    dependencies = build_dependent_packages({'pyyaml': '1.0.0', 'puka': None, 'pyasn1': '2.0.0'},
                                            'versions.cfg')

    build_with_fpm_calls = [call('puka', version=None),
                            call('pyyaml', version='1.0.0'),
                            call('pyasn1', version='2.0.0')]
    mock_build_with_fpm.assert_has_calls(build_with_fpm_calls)

    assert dependencies == {'fabric': '1.0.0', 'setuptools': '2.0.0',
                            'paramiko': '3.0.0', 'requests': None}


def test_download_package_with_version(monkeypatch):
    mock_pip_main = Mock()
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.pip.main', mock_pip_main)

    download_package('puka', '1.0.0', '/tmp/123/')

    expected_call = ['install', '-q', 'puka==1.0.0', '--ignore-installed',
                     '--no-install', '--build=/tmp/123/']
    mock_pip_main.assert_called_once_with(expected_call)


def test_download_package_without_version(monkeypatch):
    mock_pip_main = Mock()
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.pip.main', mock_pip_main)

    download_package('pyyaml', None, '/tmp/123/')

    expected_call = ['install', '-q', 'pyyaml', '--ignore-installed',
                     '--no-install', '--build=/tmp/123/']
    mock_pip_main.assert_called_once_with(expected_call)


def test_ruby_to_json(monkeypatch):
    mock_subprocess_check_output = Mock(return_value='{}')
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.subprocess.check_output',
                        mock_subprocess_check_output)

    ruby_to_json('{:timestamp=>"2015-04-02T14:17:29.101257+0200", :message=>"Created package", :path=>"python-elasticsearch-curator_3.0.3_all.deb"}')

    mock_subprocess_check_output.assert_called_once_with(['ruby', '-e',
                                                          'require "json"; puts JSON.generate({:timestamp=>"2015-04-02T14:17:29.101257+0200", :message=>"Created package", :path=>"python-elasticsearch-curator_3.0.3_all.deb"})'])


def test_read_dependencies_package(monkeypatch):
    mock_subprocess_check_output = Mock(return_value=sentinel.some_string)
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.subprocess.check_output',
                        mock_subprocess_check_output)

    dependencies = ['python-yaml == 1.0.0', 'python-zmq <= 2.0.0', 'python-crypto << 3.0.0',
                    'python-package_1 >= 4.0.0', 'packAge_2 >> 5.0.0', 'package_3 != 6.0.0',
                    'package_4 = 7.0.0', 'python', 'Python']

    mock_parse_from_dpkg_output = Mock(return_value=dependencies)
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.parse_from_dpkg_output',
                        mock_parse_from_dpkg_output)

    result = read_dependencies_package('puka')

    expected_result = ['pyyaml', 'pyzmq', 'pycrypto', 'package_1', 'package_2', 'package_3',
                       'package_4']

    mock_subprocess_check_output.assert_called_once_with(['dpkg', '-f', 'puka', 'Depends'])
    mock_parse_from_dpkg_output.assert_called_once_with(sentinel.some_string)

    assert result == expected_result


def test_parse_from_dpkg_output():
    result = parse_from_dpkg_output('erlang-nox (>= 1:13.b.3), adduser (= 3.1), logrotate')
    expected_result = ['erlang-nox >= 1:13.b.3', ' adduser = 3.1', ' logrotate']
    assert result == expected_result


def test_fpm_command_dependencies_and_extra_args(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.path.join',
                        Mock(return_value='files/preremove'))

    result = fpm_command('test', './home/test/setup.py',
                         no_python_dependencies=True,
                         extra_args=['-d', 'test'])

    expected_result = ['fpm', '-s', 'python', '-t', 'deb', '-f', '--maintainer=CSI',
                       '--exclude=*.pyc', '--exclude=*.pyo', '--depends=python',
                       '--category=python', '--python-bin=/usr/bin/python',
                       '--template-scripts',
                       '--python-install-lib=/usr/lib/python2.7/dist-packages/',
                       '--python-install-bin=/usr/local/bin/',
                       '--before-remove=files/preremove', '--no-python-dependencies',
                       '-d', 'test', './home/test/setup.py']

    assert sorted(result) == sorted(expected_result)


def test_fpm_command_dependencies_and_no_extra_args(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.path.join',
                        Mock(return_value='files/preremove'))

    result = fpm_command('test', './home/test/setup.py',
                         no_python_dependencies=True)

    expected_result = ['fpm', '-s', 'python', '-t', 'deb', '-f', '--maintainer=CSI',
                       '--exclude=*.pyc', '--exclude=*.pyo', '--depends=python',
                       '--category=python', '--python-bin=/usr/bin/python',
                       '--template-scripts',
                       '--python-install-lib=/usr/lib/python2.7/dist-packages/',
                       '--python-install-bin=/usr/local/bin/',
                       '--before-remove=files/preremove', '--no-python-dependencies',
                       './home/test/setup.py']

    assert sorted(result) == sorted(expected_result)


def test_fpm_command_no_dependencies_and_no_extra_args(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.path.join',
                        Mock(return_value='files/preremove'))

    result = fpm_command('test', './home/test/setup.py')

    expected_result = ['fpm', '-s', 'python', '-t', 'deb', '-f', '--maintainer=CSI',
                       '--exclude=*.pyc', '--exclude=*.pyo', '--depends=python',
                       '--category=python', '--python-bin=/usr/bin/python',
                       '--template-scripts',
                       '--python-install-lib=/usr/lib/python2.7/dist-packages/',
                       '--python-install-bin=/usr/local/bin/',
                       '--before-remove=files/preremove', './home/test/setup.py']

    assert sorted(result) == sorted(expected_result)


def test_fpm_command_broken_scheme(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.path.join',
                        Mock(return_value='files/preremove'))

    result = fpm_command('pyyaml', './home/test/setup.py')

    expected_result = ['fpm', '--name', 'python-yaml', '-s', 'python', '-t', 'deb', '-f',
                       '--maintainer=CSI', '--exclude=*.pyc', '--exclude=*.pyo',
                       '--depends=python', '--category=python', '--python-bin=/usr/bin/python',
                       '--template-scripts',
                       '--python-install-lib=/usr/lib/python2.7/dist-packages/',
                       '--python-install-bin=/usr/local/bin/',
                       '--before-remove=files/preremove', './home/test/setup.py']

    assert sorted(result) == sorted(expected_result)


def test_fpm_command_version(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.path.join',
                        Mock(return_value='files/preremove'))

    result = fpm_command('pyyaml', './home/test/setup.py', version='1.2.0-jenkins-704')

    expected_result = ['fpm', '--name', 'python-yaml', '-s', 'python', '-t', 'deb', '-f',
                       '--version=1.2.0-jenkins-704', '--maintainer=CSI', '--exclude=*.pyc',
                       '--exclude=*.pyo', '--depends=python', '--category=python',
                       '--python-bin=/usr/bin/python', '--template-scripts',
                       '--python-install-lib=/usr/lib/python2.7/dist-packages/',
                       '--python-install-bin=/usr/local/bin/',
                       '--before-remove=files/preremove', './home/test/setup.py']

    assert sorted(result) == sorted(expected_result)


def test_fpm_command_version_hotfix(monkeypatch):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.os.path.join',
                        Mock(return_value='files/preremove'))

    result = fpm_command('pyyaml', './home/test/setup.py', version='1.2.0-jenkins-704', iteration=1)

    expected_result = ['fpm', '--name', 'python-yaml', '-s', 'python', '-t', 'deb', '-f',
                       '--version=1.2.0-jenkins-704.1', '--maintainer=CSI', '--exclude=*.pyc',
                       '--exclude=*.pyo', '--depends=python', '--category=python',
                       '--python-bin=/usr/bin/python', '--template-scripts',
                       '--python-install-lib=/usr/lib/python2.7/dist-packages/',
                       '--python-install-bin=/usr/local/bin/',
                       '--before-remove=files/preremove', './home/test/setup.py']

    assert sorted(result) == sorted(expected_result)


def test_read_dependencies(mock_logger):
    file_name = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'files/setup.py')

    result = sorted(read_dependencies_setup_py(file_name))

    expected_result = sorted(['setuptools', 'pyyaml', 'puka', 'couchbase'])

    assert result == expected_result


def test_extend_extra_args_with_versions(mock_logger):
    extra_args = ['--test-1', '--test-2']
    dependencies_with_versions = {'setuptools': '1.0.0', 'puka': '2.0.0'}

    result = sorted(extend_extra_args(extra_args, dependencies_with_versions))

    expected_result = sorted(['--test-1', '--test-2',
                              '-d', 'python-setuptools >= 1.0.0',
                              '-d', 'python-puka >= 2.0.0'])

    assert result == expected_result


def test_extend_extra_args_without_versions(mock_logger):
    extra_args = ['--test-1', '--test-2']
    dependencies_with_versions = {'setuptools': None, 'puka': None}

    result = sorted(extend_extra_args(extra_args, dependencies_with_versions))

    expected_result = sorted(['--test-1', '--test-2',
                              '-d', 'python-setuptools',
                              '-d', 'python-puka'])

    assert result == expected_result


def test_extend_extra_args_broken_scheme(mock_logger):
    extra_args = ['--test-1', '--test-2']
    dependencies_with_versions = {'pyyaml': None, 'pyzmq': '1.0.0'}

    result = sorted(extend_extra_args(extra_args, dependencies_with_versions))

    expected_result = sorted(['--test-1', '--test-2',
                              '-d', 'python-yaml',
                              '-d', 'python-zmq >= 1.0.0'])

    assert result == expected_result


def _side_effect_get(_, dependency):
    if dependency == 'pyyaml':
        return '1.0.0'
    elif dependency == 'puka':
        return '2.0.0'
    elif dependency == 'setuptools':
        return '3.0.0'


def _side_effect_has_option(_, dependency):
    if dependency == 'pyyaml':
        return True
    elif dependency == 'puka':
        return True
    elif dependency == 'setuptools':
        return True


def test_lookup_versions(monkeypatch, mock_logger):
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.ConfigParser.ConfigParser.has_option',
                        Mock(side_effect=_side_effect_has_option))
    monkeypatch.setattr('vdt.versionplugin.buildout.shared.ConfigParser.ConfigParser.get',
                        Mock(side_effect=_side_effect_get))

    result = lookup_versions(['pyyaml', 'puka', 'setuptools', 'pyzmq'], 'versions.cfg')

    expected_result = {'pyyaml': '1.0.0', 'puka': '2.0.0',
                       'setuptools': '3.0.0', 'pyzmq': None}

    assert result == expected_result


def test_parse_version_extra_args():
    args, extra_args = parse_version_extra_args(['--include', 'test1', '-i', 'test2',
                                                 '--versions-file', '/home/test/versions.cfg',
                                                 '-d', '--test1', '-d', '--test2',
                                                 '--iteration=1'])
    assert sorted(args.include) == sorted(['test1', 'test2'])
    assert args.versions_file == '/home/test/versions.cfg'
    assert args.iteration == '1'
    assert sorted(extra_args) == sorted(['-d', '--test1', '-d', '--test2'])