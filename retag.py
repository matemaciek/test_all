#!/usr/bin/python
import argparse
import os
import subprocess
import semantic_version
import sys

base_path = ""
base_repo = ""
root_repo = ""
children_file = ""

doable_forest_cache = {}


def split_output(*command):
    """
    @param command: command (may be with arguments) to execute
    @return: list of lines of standard output of running command
    """
    return subprocess.check_output(command).split("\n")


def enter_repo(repo):
    """
    enters repository
    @param repo: repository to enter
    """
    path = os.path.join(base_path, base_repo)
    if repo != base_repo:
        path = os.path.join(path, repo)
    os.chdir(path)


def all_vers(repo):
    """
    @param repo: repository to check
    @return: all tagged versions in this repo
    """
    enter_repo(repo)
    tags = split_output("git", "tag", "-l")
    result = []
    for tag in tags:
        if semantic_version.validate(tag):
            result.append(semantic_version.Version(tag))
    return result


def checkout(repo, ref):
    """
    @param repo: repository to checkout
    @param ref: reference to checkout
    """
    enter_repo(repo)
    subprocess.check_call(["git", "checkout", ref])


def children(repo):
    """
    @param repo: repository to check
    @return: list of pairs (child repository), required minimum version) - from file named children_file in repo
    """
    enter_repo(repo)
    if not os.path.exists(children_file):
        return []
    result = []
    for child in split_output("cat", children_file):
        try:
            child_repo, child_ver = child.split(",")
        except ValueError:
            continue
        result.append((child_repo, semantic_version.Version(child_ver)))
    return result


def best_ver(required_ver, available_vers):
    """
    @param required_ver: required minimum version
    @param available_vers: list of possible versions to chose from
    @return: highest available version with the same Major version as required version
    """
    s = semantic_version.Spec(">={0}".format(str(required_ver)), "<{0}".format(str(required_ver.major + 1)))
    return s.select(available_vers)


def doable_forest(repo):
    """
    @param repo: repository to treat as root
    @return: forest map of achievable versions: version -> tree of compatible descendants' versions
    """
    if repo in doable_forest_cache:
        return doable_forest_cache[repo]
    enter_repo(repo)
    vers = all_vers(repo)
    result = {}
    for ver in vers:
        old_ref = split_output("git", "describe", "--all")[0]
        checkout(repo, str(ver))
        kids = children(repo)
        kids_forests = {}
        for kid in kids:
            (kid_repo, kid_required_ver) = kid
            kid_forest = doable_forest(kid_repo)
            kid_doable_vers = kid_forest.keys()
            kid_ver = best_ver(kid_required_ver, kid_doable_vers)
            if kid_ver is None:
                break
            kids_forests[kid_repo] = {"version": kid_ver, "children": kid_forest[kid_ver][kid_repo]["children"]}
        else:
            result[ver] = {repo: {"version": ver, "children": kids_forests}}
        checkout(repo, old_ref)
    doable_forest_cache[repo] = result
    return result


def cut_the_tree(tree, dictionary):
    """
    @param tree: tree of settled descendants' versions
    @param dictionary: dictionary to put result into
    @return: configuration - map (repository -> version) supplemented with new versions from tree
    """
    for key in tree.keys():
        dictionary[key] = tree[key]["version"]
        cut_the_tree(tree[key]["children"], dictionary)
    return dictionary


def cut_the_trees(forest):
    """
    @param forest: forest map of achievable versions
    @return: list of corresponding configurations
    """
    snags = []
    for key in forest.keys():
        snags.append(cut_the_tree(forest[key], {}))
    return snags


def doable_str(snags):
    """
    @param snags: list of configurations
    @return: pretty printed configurations
    """
    result = ""
    for snag in snags:
        result += "{\n"
        for key in snag.keys():
            result += "\t{0},{1}\n".format(key, snag[key])
        result += "}\n"
    return result


def best_snag(snags):
    """
    @param snags: list of configurations
    @return: best configuration
    """
    vers = [snag[root_repo] for snag in snags]
    best_v = semantic_version.Spec(">=0.0.0").select(vers)
    try:
        result = next(snag for snag in snags if snag[root_repo] == best_v)
    except StopIteration:
        print "No suitable configuration found, dying..."
        raise
    return result


def best_conf():
    """
    @return: best achievable configuration for root_repo
    """
    return best_snag(cut_the_trees(doable_forest(root_repo)))


def set_conf(conf):
    """
    Sets configuration in all submodules of base_repo
    @param conf: configuration to be set
    """
    for repo in conf.keys():
        print "checking out {0} in version {1}".format(repo, str(conf[repo]))
        checkout(repo, str(conf[repo]))


def commit_conf(conf):
    """
    Sets configuration in all submodules of base_repo and commits it
    @param conf: configuration to be set
    """
    set_conf(conf)
    enter_repo(base_repo)
    msg = "autocommit using new configuration\n{0}"
    msg_conf = ""
    for repo in sorted(conf.keys()):
        msg_conf += "{0},{1}\n".format(repo, str(conf[repo]))
    if subprocess.call(["git", "diff-index", "--quiet", "HEAD"]) == 1:
        print "Upgrading to new, better configuration."
        subprocess.check_call(["git", "commit", "-a", "-m", msg.format(msg_conf)])
        subprocess.check_call(["git", "push"])
    else:
        print "Nihil sub sole novum, exiting."


parser = argparse.ArgumentParser(description='Chooses newest configuration for repository tree.')
parser.add_argument("base_path", help="path where base repository is")
parser.add_argument("base_repo", help="name of the base repository")
parser.add_argument("root_repo", help="name of the root repository")
parser.add_argument("-children_file",
                    help="name of the file containing children's versions information (default: children.txt)",
                    default="children.txt")
args = parser.parse_args()
base_path = args.base_path
base_repo = args.base_repo
root_repo = args.root_repo
children_file = args.children_file

commit_conf(best_conf()) # TODO: resolve issues with commit and push (it get messed up when called via chef)
#set_conf(best_conf())
