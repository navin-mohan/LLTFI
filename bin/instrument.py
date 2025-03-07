#! /usr/bin/env python3

"""

%(prog)s takes a single IR file as input and generates IR files (and executables, depending on the -IRonly option) with instrumented profiling and fault injection function calls

Usage: %(prog)s [OPTIONS] <source IR file>

List of options:

--dir <relative directory>: Generate the instrumented IRs and executables to '<directory of source IR file>/<relative directory>', default: llfi
-L <library directory>:     Add <library directory> to the search directories for -l
-l<library>:                link <library>
--readable:                 Generate human-readable IR files
--IRonly:                   Only generate the instrumented IR files, and you will do the linking and create the executables manually
--verbose:                  Show verbose information
--help(-h):                 Show help information
--use-ml-specific-rt        Use ML-Specific FI runtime, that statically-links with the ML application to speedup the FI.

Prerequisite:
You need to have 'input.yaml' under the same directory as <source IR file>, which contains appropriate options for LLFI
"""

# Everytime the contents of compileOption is changed in input.yaml
# this script should be run to create new fi.exe and prof.exe

import sys, os, shutil
import yaml
import subprocess

script_path = os.path.realpath(os.path.dirname(__file__))
sys.path.append(os.path.join(script_path, '../config'))
import llvm_paths


optbin = os.path.join(llvm_paths.LLVM_DST_ROOT, "bin/opt")
llcbin = os.path.join(llvm_paths.LLVM_DST_ROOT, "bin/llc")
llvmgcc = os.path.join(llvm_paths.LLVM_GXX_BIN_DIR, "clang")
llvmgxx = os.path.join(llvm_paths.LLVM_GXX_BIN_DIR, "clang++")
llfilinklib = os.path.join(script_path, "../runtime_lib")
defaultlinklibs = ['-lpthread']
prog = os.path.basename(sys.argv[0])
# basedir is assigned in parseArgs(args)
basedir = ""

# llfibd = os.path.join(basedir, "llfi")
# if os.path.exists(llfibd):
#   shutil.rmtree(llfibd)

if sys.platform == "linux" or sys.platform == "linux2":
  llfilib = os.path.join(script_path, "../llvm_passes/llfi-passes.so")
elif sys.platform == "darwin":
  llfilib = os.path.join(script_path, "../llvm_passes/llfi-passes.dylib")
else:
  print("ERROR: LLFI does not support platform " + sys.platform + ".")
  exit(1)


options = {
  "dir": "llfi",
  "source": "",
  "L": [],
  "l": [],
  "readable": False,
  "verbose": False,
  "IRonly": False,
  "genDotGraph": False,
  "useMLSpecificRT": False,
}


def usage(msg = None):
  retval = 0
  if msg is not None:
    retval = 1
    msg = "ERROR: " + msg
    print(msg, file=sys.stderr)
  print(__doc__ % globals(), file=sys.stderr)
  sys.exit(retval)


def verbosePrint(msg, verbose):
  if verbose:
    print(msg)


def parseArgs(args):
  global options
  argid = 0
  while argid < len(args):
    arg = args[argid]
    if arg.startswith("-"):
      if arg == "--dir":
        if options["dir"] != "llfi":
          usage("Duplicated argument: " + arg)
        argid += 1
        options["dir"] = args[argid].rstrip('/')
      elif arg == "-L":
        argid += 1
        options["L"].append(os.path.abspath(os.path.join(os.getcwd(), args[argid])))
      elif arg.startswith("-l"):
        options["l"].append(arg[2:])
      elif arg == "--readable":
        options["readable"] = True
      elif arg == "--verbose":
        options["verbose"] = True
      elif arg == "--IRonly":
        options["IRonly"] = True
      elif arg == "--use-ml-specific-rt":
        options["useMLSpecificRT"] = True
      elif arg == "--help" or arg == "-h":
        usage()
      else:
        usage("Invalid argument: " + arg)
    else:
      if options["source"] != "":
        usage("More than one source files are specified")
      options["source"] = os.path.abspath(os.path.join(os.getcwd(), arg))
      basedir = os.path.dirname(options["source"])
      if basedir != os.path.abspath(os.getcwd()):
        print("Change directory to:", basedir)
        os.chdir(basedir)
    argid += 1

  if options["source"] == "":
    usage("No input IR file specified")

  if '/' in options["dir"]:
    usage("Cannot specify embedded directories for --dir")
  else:
    srcpath = os.path.dirname(options["source"])
    fullpath = os.path.join(srcpath, options["dir"])
    if os.path.exists(fullpath):
      usage(options["dir"] + " already exists under " + srcpath + \
            ", you can either specify a different directory for --dir or " +\
            "remove " + options["dir"] + " from " + srcpath)
    else:
      try:
        os.mkdir(fullpath)
        options["dir"] = fullpath
      except:
        usage("Unable to create a directory named " + options["dir"] +\
              " under " + srcpath)


def checkInputYaml():
  #Check for input.yaml's presence
  global cOpt
  srcpath = os.path.dirname(options["source"])
  try:
    f = open(os.path.join(srcpath, 'input.yaml'), 'r')
  except:
    print("ERROR: No input.yaml file in the %s directory." % srcpath)
    os.rmdir(options["dir"])
    exit(1)

  #Check for input.yaml's correct formmating
  try:
    doc = yaml.load(f)
    f.close()
    verbosePrint(yaml.dump(doc), options["verbose"])
  except:
    print("Error: input.yaml is not formatted in proper YAML (reminder: use spaces, not tabs)")
    os.rmdir(options["dir"])
    exit(1)

  #Check for compileOption in input.yaml
  try:
    cOpt = doc["compileOption"]
  except:
    os.rmdir(options["dir"])
    print("ERROR: Please include compileOptions in input.yaml.")
    exit(1)



################################################################################
def execCompilation(execlist):
  verbosePrint(' '.join(execlist), options["verbose"])
  p = subprocess.Popen(execlist)
  p.wait()
  return p.returncode

################################################################################
def readCompileOption():
  global compileOptions

  ###Instruction selection method
  if "instSelMethod" not in cOpt:
    print(("\n\nERROR: Please include an 'instSelMethod' key value pair under compileOption in input.yaml.\n"))
    exit(1)
  else:
    compileOptions = []
    validMethods = ["insttype", "funcname", "customInstselector"]
    # Generate list of instruction selection methods
    # TODO: Generalize and document
    instSelMethod = cOpt["instSelMethod"]
    for method in instSelMethod:
      methodName = list(method.keys())[0]
      if methodName not in validMethods:
        print ("\n\nERROR: Unknown instruction selection method in input.yaml.\n")
        exit(1)

    #Select by instruction type
    if methodName == "insttype" or methodName == "funcname":
        compileOptions.append("-%s" % (str(methodName)))
    #Select by custom instruction
    elif methodName == "customInstselector":
      compileOptions = ['-custominstselector']

    # Ensure that 'include' is specified at least
    # TODO: This isn't a very extendible way of doing this.
    if "include" not in method[methodName]:
      print(("\n\nERROR: An 'include' list must be present for the %s method in input.yaml.\n" % (methodName)))
      exit(1)

    # Parse all options for current method
    custom_instselector_defined = False
    for attr in list(method[methodName].keys()):
      if(attr == "include" or attr == "exclude"):
        prefix = "-%s" % (str(attr))
        if methodName == "insttype":
          prefix += "inst="
        elif methodName == "funcname":
          prefix += "func="
        elif methodName == "customInstselector":
          prefix = "-fiinstselectorname="
          # For customInstselector, only one instruction selector is allowed
          if custom_instselector_defined == True:
            print("\nERROR: '\'instrument\' only support one customInstselector included in input.yaml.")
            print("To apply a list of fault models/failure modes, please use \'batchinstrument\'")
            exit(1)
          else:
            custom_instselector_defined = True
        else: # add the ability to give custom options here?
          pass
        # Generate list of options for attribute
        opts = [prefix + opt for opt in method[methodName][attr]]
        compileOptions.extend(opts)
      elif(attr == "options"):
        opts = [opt for opt in method[methodName]["options"]]
        compileOptions.extend(opts)

  ###Register selection method
  if "regSelMethod" not in cOpt:
    print(("\n\nERROR: Please include an 'regSelMethod' key value pair under compileOption in input.yaml.\n"))
    exit(1)
  else:
    #Select by register location
    if cOpt["regSelMethod"] == 'regloc':
      compileOptions.append('-regloc')
      if "regloc" not in cOpt:
        print(("\n\nERROR: An 'regloc' key value pair must be present for the regloc method in input.yaml.\n"))
        exit(1)
      else:
        compileOptions.append('-'+cOpt["regloc"])

    #Select by custom register
    elif cOpt["regSelMethod"]  == 'customregselector':
      compileOptions.append('-customregselector')
      if "customRegSelector" not in cOpt:
        print(("\n\nERROR: An 'customRegSelector' key value pair must be present for the customregselector method in input.yaml.\n"))
        exit(1)
      else:
          if cOpt["customRegSelector"] == "SoftwareFault" or cOpt["customRegSelector"] == "Automatic":
            ## replace the Automatic tag with the customInstSelector name
            try:
              regselectorname = cOpt["instSelMethod"][0]["customInstselector"]["include"][0]
            except:
              print("\n\nERROR: Cannot extract customRegSelector from instSelMethod. Please check the customInstselector field in input.yaml\n")
            else:
              compileOptions.append('-firegselectorname='+regselectorname)
          else:
            compileOptions.append('-firegselectorname='+cOpt["customRegSelector"])
          if "customRegSelectorOption" in cOpt:
            for opt in cOpt["customRegSelectorOption"]:
              compileOptions.append(opt)

    else:
      print(("\n\nERROR: Unknown Register selection method in input.yaml.\n"))
      exit(1)

  ###Injection Trace selection
  if "includeInjectionTrace" in cOpt:
    for trace in cOpt["includeInjectionTrace"]:
      if trace == 'forward':
        compileOptions.append('-includeforwardtrace')
      elif trace == 'backward':
        compileOptions.append('-includebackwardtrace')
      else:
        print(("\n\nERROR: Invalid value for trace (forward/backward allowed) in input.yaml.\n"))
        exit(1)

  ###Tracing Proppass
  if "tracingPropagation" in cOpt and cOpt["tracingPropagation"] == True:
    print(("\nWARNING: You enabled 'tracingPropagation' option in input.yaml. "
           "The generate executables will be able to output dynamic values for instructions. "
           "However, the executables take longer time to execute. If you don't want the trace, "
           "please disable the option and re-run %s." %prog))
    compileOptions.append('-insttracepass')
    if 'tracingPropagationOption' in cOpt:
      if "debugTrace" in cOpt["tracingPropagationOption"]:
        if(str(cOpt["tracingPropagationOption"]["debugTrace"]).lower() == "true"):
          compileOptions.append('-debugtrace')
      if "maxTrace" in cOpt["tracingPropagationOption"]:
        assert isinstance(cOpt["tracingPropagationOption"]["maxTrace"], int)==True, "maxTrace must be an integer in input.yaml"
        assert int(cOpt["tracingPropagationOption"]["maxTrace"])>0, "maxTrace must be greater than 0 in input.yaml"
        compileOptions.append('-maxtrace')
        compileOptions.append(str(cOpt["tracingPropagationOption"]["maxTrace"]))

      ###Dot Graph Generation selection
      if "generateCDFG" in cOpt["tracingPropagationOption"]:
          if (str(cOpt["tracingPropagationOption"]["generateCDFG"]).lower() == "true"):
            options["genDotGraph"] = True

################################################################################
def _suffixOfIR():
  if options["readable"]:
    return ".ll"
  else:
    return ".bc"

def compileProg():
  global proffile, fifile, compileOptions, defaultlinklibs
  srcbase = os.path.basename(options["source"])
  progbin = os.path.join(options["dir"], srcbase[0 : srcbase.rfind(".")])

  llfi_indexed_file = progbin + "-llfi_index"
  proffile = progbin + "-profiling"
  fifile = progbin + "-faultinjection"
  tmpfiles = []

  execlist = [optbin, '-load-pass-plugin', llfilib, '-genllfiindexpass', '-o',
              llfi_indexed_file + _suffixOfIR(), options['source']]
  if options["readable"]:
    execlist.append('-S')
  if options["genDotGraph"]:
    execlist.append('-dotgraphpass')
  retcode = execCompilation(execlist)

  if retcode == 0:
    execlist = [optbin, '-load-pass-plugin', llfilib, '-profilingpass']
    execlist2 = ['-o', proffile + _suffixOfIR(), llfi_indexed_file + _suffixOfIR()]
    execlist.extend(compileOptions)
    execlist.extend(execlist2)
    if options["readable"]:
      execlist.append("-S")
    retcode = execCompilation(execlist)

  if retcode == 0:
    execlist = [optbin, '-load-pass-plugin', llfilib, '-faultinjectionpass']
    execlist2 = ['-o', fifile + _suffixOfIR(), llfi_indexed_file + _suffixOfIR()]
    execlist.extend(compileOptions)
    execlist.extend(execlist2)
    #print(execlist)
    if options["readable"]:
      execlist.append("-S")
    retcode = execCompilation(execlist)

  if retcode != 0:
    print("\nERROR: there was an error during running the "\
                      "instrumentation pass, please follow"\
                      " the provided instructions for %s." % prog, file=sys.stderr)
    shutil.rmtree(options['dir'], ignore_errors = True)
    sys.exit(retcode)

  if not options["IRonly"]:
    if retcode == 0:
      execlist = [llcbin, '-filetype=obj', '-o', proffile + '.o', proffile + _suffixOfIR()]
      tmpfiles.append(proffile + '.o')
      retcode = execCompilation(execlist)
    if retcode == 0:
      execlist = [llcbin, '-filetype=obj', '-o', fifile + '.o', fifile + _suffixOfIR()]
      tmpfiles.append(fifile + '.o')
      retcode = execCompilation(execlist)

    liblist = list(defaultlinklibs)
    for lib_dir in options["L"]:
      liblist.extend(["-L", lib_dir])
    for lib in options["l"]:
      liblist.append("-l" + lib)
    liblist.append("-no-pie")
    liblist.append("-Wl,-rpath")
    liblist.append(llfilinklib)

    if retcode == 0:
      execlist = [llvmgcc, '-o', proffile + '.exe', proffile + '.o', '-L'+llfilinklib]

      # Check whether we should use static or dynamic FI RT
      execlist.extend(["-lllfi-rt"])
      execlist.extend(liblist)
      retcode = execCompilation(execlist)
      if retcode != 0:
        print("...Error compiling with " + os.path.basename(llvmgcc) + ", trying with " + os.path.basename(llvmgxx) + ".")
        execlist[0] = llvmgxx
        retcode = execCompilation(execlist)
    if retcode == 0:
      execlist = [llvmgcc, '-o', fifile + '.exe', fifile + '.o', '-L'+llfilinklib]

      # Check whether we should use static or dynamic FI RT
      if options['useMLSpecificRT']:
          execlist.extend(["-lml-lltfi-rt"])
      else:
          execlist.extend(["-lllfi-rt"])

      execlist.extend(liblist)
      retcode = execCompilation(execlist)
      if retcode != 0:
        print("...Error compiling with " + os.path.basename(llvmgcc) + ", trying " + os.path.basename(llvmgxx) + ".")
        execlist[0] = llvmgxx
        retcode = execCompilation(execlist)


    for tmpfile in tmpfiles:
      try:
        os.remove(tmpfile)
      except:
        pass
    if retcode != 0:
      print("\nERROR: there was an error during linking and generating executables,"\
                           "Please take %s and %s and generate the executables manually (linking llfi-rt "\
                           "in directory %s)." %(proffile + _suffixOfIR(), fifile + _suffixOfIR(), llfilinklib), file=sys.stderr)
      sys.exit(retcode)
    else:
      print("\nSuccess", file=sys.stderr)


################################################################################
def main(args):
  parseArgs(args)
  checkInputYaml()
  readCompileOption()
  compileProg()

################################################################################

if __name__=="__main__":
  main(sys.argv[1:])
