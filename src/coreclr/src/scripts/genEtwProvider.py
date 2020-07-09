##
## Licensed to the .NET Foundation under one or more agreements.
## The .NET Foundation licenses this file to you under the MIT license.
##
## This script generates the interface to ETW using MC.exe

import os
from os import path
import shutil
import re
import sys
import argparse
import subprocess
import xml.dom.minidom as DOM
from genEventing import parseTemplateNodes
from utilities import open_for_update, update_directory, parseExclusionList

macroheader_filename = "etwmacros.h"
mcheader_filename = "ClrEtwAll.h"
clrxplat_filename = "clrxplatevents.h"
etw_dirname = "etw"
replacements = [
    (r"EventEnabled", "EventXplatEnabled"),
    (r"\bPVOID\b", "void*"),
]
counted_replacements = [
    # There is a bug in the MC code generator that miscomputes the size of ETW events
    # which have variable size arrays of variable size arrays. This occurred in our GCBulkType
    # event. This workaround replaces the bad size computation with the correct one. See
    # https://github.com/dotnet/coreclr/pull/25454 for more information"
    (r"_Arg0 \* _Arg2_Len_", "_Arg2_Len_", 1)
]

stdprolog_cpp="""
// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.

/******************************************************************

DO NOT MODIFY. AUTOGENERATED FILE.
This file is generated using the logic from <root>/src/scripts/genEtwProvider.py

******************************************************************/
"""

def genProviderInterface(manifest, intermediate):
    provider_dirname = os.path.join(intermediate, etw_dirname + "_temp")

    if not os.path.exists(provider_dirname):
        os.makedirs(provider_dirname)

    cmd = ['mc.exe', '-h', provider_dirname, '-r', provider_dirname, '-b', '-co', '-um', '-p', 'FireEtXplat', manifest]
    subprocess.check_call(cmd)

    header_text = None
    with open(path.join(provider_dirname, mcheader_filename), 'r') as mcheader_file:
        header_text = mcheader_file.read()

    for pattern, replacement in replacements:
        header_text = re.sub(pattern, replacement, header_text)

    for pattern, replacement, expected_count in counted_replacements:
        (header_text, actual_count) = re.subn(pattern, replacement, header_text)
        if actual_count != expected_count:
            raise Exception("The workaround for https://github.com/dotnet/coreclr/pull/25454 in src/scripts/genEtwProvider.py could not be applied. Has the generated code changed or perhaps the underlying issue has been fixed? ")

    with open(path.join(provider_dirname, mcheader_filename), 'w') as mcheader_file:
        mcheader_file.write(header_text)

def genXplatHeader(intermediate):
    with open_for_update(path.join(intermediate, clrxplat_filename)) as header_file:
        header_file.write("""
#ifndef _CLR_XPLAT_EVENTS_H_
#define _CLR_XPLAT_EVENTS_H_

#include "{0}/{1}"
#include "{0}/{2}"

#endif //_CLR_XPLAT_EVENTS_H_
""".format(etw_dirname, macroheader_filename, mcheader_filename))

def getStackWalkBit(eventProvider, taskName, eventSymbol, stackSet):
    for entry in stackSet:
        tokens = entry.split(':')

        if len(tokens) != 3:
            raise Exception("Error, possible error in the script which introduced the entry "+ entry)

        eventCond  = tokens[0] == eventProvider or tokens[0] == "*"
        taskCond   = tokens[1] == taskName      or tokens[1] == "*"
        symbolCond = tokens[2] == eventSymbol   or tokens[2] == "*"

        if eventCond and taskCond and symbolCond:
            return False
    return True

#Add the miscellaneous checks here
def checkConsistency(manifest, exclusion_filename):
    tree                      = DOM.parse(manifest)
    exclusionInfo = parseExclusionList(exclusion_filename)
    for providerNode in tree.getElementsByTagName('provider'):

        stackSupportSpecified = {}
        eventNodes            = providerNode.getElementsByTagName('event')
        templateNodes         = providerNode.getElementsByTagName('template')
        eventProvider         = providerNode.getAttribute('name')
        allTemplates          = parseTemplateNodes(templateNodes)

        for eventNode in eventNodes:
            taskName         = eventNode.getAttribute('task')
            eventSymbol      = eventNode.getAttribute('symbol')
            eventTemplate    = eventNode.getAttribute('template')
            eventValue       = int(eventNode.getAttribute('value'))
            clrInstanceBit   = getStackWalkBit(eventProvider, taskName, eventSymbol, exclusionInfo.noclrinstance)
            sLookupFieldName = "ClrInstanceID"
            sLookupFieldType = "win:UInt16"

            if clrInstanceBit and allTemplates.get(eventTemplate):
                # check for the event template and look for a field named ClrInstanceId of type win:UInt16
                fnParam = allTemplates[eventTemplate].getFnParam(sLookupFieldName)

                if not(fnParam and fnParam.winType == sLookupFieldType):
                    raise Exception(exclusion_filename + ":No " + sLookupFieldName + " field of type " + sLookupFieldType + " for event symbol " +  eventSymbol)

            # If some versions of an event are on the nostack/stack lists,
            # and some versions are not on either the nostack or stack list,
            # then developer likely forgot to specify one of the versions

            eventStackBitFromNoStackList       = getStackWalkBit(eventProvider, taskName, eventSymbol, exclusionInfo.nostack)
            eventStackBitFromExplicitStackList = getStackWalkBit(eventProvider, taskName, eventSymbol, exclusionInfo.explicitstack)
            sStackSpecificityError = exclusion_filename + ": Error processing event :" + eventSymbol + "(ID" + str(eventValue) + "): This file must contain either ALL versions of this event or NO versions of this event. Currently some, but not all, versions of this event are present\n"

            if not stackSupportSpecified.get(eventValue):
                 # Haven't checked this event before.  Remember whether a preference is stated
                if ( not eventStackBitFromNoStackList) or ( not eventStackBitFromExplicitStackList):
                    stackSupportSpecified[eventValue] = True
                else:
                    stackSupportSpecified[eventValue] = False
            else:
                # We've checked this event before.
                if stackSupportSpecified[eventValue]:
                    # When we last checked, a preference was previously specified, so it better be specified here
                    if eventStackBitFromNoStackList and eventStackBitFromExplicitStackList:
                        raise Exception(sStackSpecificityError)
                else:
                    # When we last checked, a preference was not previously specified, so it better not be specified here
                    if ( not eventStackBitFromNoStackList) or ( not eventStackBitFromExplicitStackList):
                        raise Exception(sStackSpecificityError)

def genEtwMacroHeader(manifest, exclusion_filename, intermediate):
    provider_dirname = os.path.join(intermediate, etw_dirname + "_temp")

    if not os.path.exists(provider_dirname):
        os.makedirs(provider_dirname)

    tree                      = DOM.parse(manifest)
    numOfProviders            = len(tree.getElementsByTagName('provider'))
    nMaxEventBytesPerProvider = 64

    exclusionInfo = parseExclusionList(exclusion_filename)

    with open_for_update(os.path.join(provider_dirname, macroheader_filename)) as header_file:
        header_file.write(stdprolog_cpp + "\n")

        header_file.write("#define NO_OF_ETW_PROVIDERS " + str(numOfProviders) + "\n")
        header_file.write("#define MAX_BYTES_PER_ETW_PROVIDER " + str(nMaxEventBytesPerProvider) + "\n")
        header_file.write("EXTERN_C SELECTANY const BYTE etwStackSupportedEvents[NO_OF_ETW_PROVIDERS][MAX_BYTES_PER_ETW_PROVIDER] = \n{\n")

        for providerNode in tree.getElementsByTagName('provider'):
            stackSupportedEvents = [0]*nMaxEventBytesPerProvider
            eventNodes = providerNode.getElementsByTagName('event')
            eventProvider    = providerNode.getAttribute('name')

            for eventNode in eventNodes:
                taskName                = eventNode.getAttribute('task')
                eventSymbol             = eventNode.getAttribute('symbol')
                eventTemplate           = eventNode.getAttribute('template')
                eventTemplate           = eventNode.getAttribute('template')
                eventValue              = int(eventNode.getAttribute('value'))
                eventIndex              = eventValue // 8
                eventBitPositionInIndex = eventValue % 8

                eventStackBitFromNoStackList       = int(getStackWalkBit(eventProvider, taskName, eventSymbol, exclusionInfo.nostack))
                eventStackBitFromExplicitStackList = int(getStackWalkBit(eventProvider, taskName, eventSymbol, exclusionInfo.explicitstack))

                # Shift those bits into position.  For the explicit stack list, swap 0 and 1, so the eventValue* variables
                # have 1 in the position iff we should issue a stack for the event.
                eventValueUsingNoStackListByPosition = (eventStackBitFromNoStackList << eventBitPositionInIndex)
                eventValueUsingExplicitStackListByPosition = ((1 - eventStackBitFromExplicitStackList) << eventBitPositionInIndex)

                # Commit the values to the in-memory array that we'll dump into the header file
                stackSupportedEvents[eventIndex] = stackSupportedEvents[eventIndex] | eventValueUsingNoStackListByPosition;
                if eventStackBitFromExplicitStackList == 0:
                    stackSupportedEvents[eventIndex] = stackSupportedEvents[eventIndex] | eventValueUsingExplicitStackListByPosition

            # print the bit array
            line = []
            line.append("\t{")
            for elem in stackSupportedEvents:
                line.append(str(elem))
                line.append(", ")

            del line[-1]
            line.append("},")
            header_file.write(''.join(line) + "\n")
        header_file.write("};\n")

def genFiles(manifest, intermediate, exclusion_filename):
    if not os.path.exists(intermediate):
        os.makedirs(intermediate)

    genProviderInterface(manifest, intermediate)
    genEtwMacroHeader(manifest, exclusion_filename, intermediate)
    genXplatHeader(intermediate)


def main(argv):
    #parse the command line
    parser = argparse.ArgumentParser(description="Generates the Code required to instrument ETW logging mechanism")

    required = parser.add_argument_group('required arguments')
    required.add_argument('--man',  type=str, required=True,
                                    help='full path to manifest containig the description of events')
    required.add_argument('--exc',  type=str, required=True,
                                    help='full path to exclusion list')
    required.add_argument('--intermediate', type=str, required=True,
                                    help='full path to eventprovider  intermediate directory')
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print('Unknown argument(s): ', ', '.join(unknown))
        return 1

    manifest           = args.man
    exclusion_filename = args.exc
    intermediate       = args.intermediate

    checkConsistency(manifest, exclusion_filename)
    genFiles(manifest, intermediate, exclusion_filename)

    # Update the final directory from temp
    provider_temp_dirname = os.path.join(intermediate, etw_dirname + "_temp")
    provider_dirname = os.path.join(intermediate, etw_dirname)
    if not os.path.exists(provider_dirname):
        os.makedirs(provider_dirname)

    update_directory(provider_temp_dirname, provider_dirname)
    shutil.rmtree(provider_temp_dirname)

if __name__ == '__main__':
    return_code = main(sys.argv[1:])
    sys.exit(return_code)
