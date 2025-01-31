# some helpful functions for use with SNAPRed script version
import yaml
from mantid.simpleapi import *

class globalParams:

# This class holds a set of parameters that will be applied during reduction
# these are stored in a YAML file and can be changed by specifying alternate
# YAML files

    def __init__(self,defaultYML):

        with open(defaultYML,'r') as file:
            ymlIn = yaml.safe_load(file)

        self.useLiteMode = ymlIn["useLiteMode"]
        self.pixelMasks = ymlIn["pixelMasks"]
        self.keepUnfocussed = ymlIn["keepUnfocussed"]
        self.convertUnitsTo = ymlIn["defaultUnfocussedWorkspaceUnits"]
        self.AN_smoothingParameter = ymlIn["artificialNorm"]["smoothingParameter"]
        self.AN_decreaseParameter = ymlIn["artificialNorm"]["decreaseParameter"]
        self.AN_lss = ymlIn["artificialNorm"]["lss"]

        return
    
def makeDefaultYML(outputYML):

    #dictionary of params
    params = {"useLiteMode": True,
              "pixelMasks": [],
              "keepUnfocussed": False,
              "defaultUnfocussedWorkspaceUnits": "dSpacing"
              }
    
    with open(outputYML, 'w') as file:
        yaml.dump(params, file)

    print('wrote: ',outputYML)

def makeSEE(outputName,SEEDirectory):

    #TODO: make function to initialise SEE (=  Sample Environment Equipment) definition with mandatory inputs
    ymlOut = SEEDirectory + outputName
    return ymlOut 

def loadSEE(seeDefinition,SEEFolder):

    #loads Parameters from SEE definition as a dictionary

    #TODO: add this to application.yml
    inputYML = f"{SEEFolder}/{seeDefinition}.yml"

    #TODO: manage errors when file doesn't exist etc.
    with open(inputYML,'r') as file:
            seeDict = yaml.safe_load(file)

    return seeDict

def reduceSNAP(runNumber,
               sampleEnv='none',
               pixelMaskIndex='none',
               YMLOverride='none',
               continueNoDifcal = False,
               continueNoVan = False,
               verbose=False):

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # SNAPRed imports
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    from snapred.backend.dao.ingredients.ArtificialNormalizationIngredients import ArtificialNormalizationIngredients
    from snapred.backend.dao.request import ReductionExportRequest
    from snapred.backend.dao.request.ReductionRequest import ReductionRequest
    from snapred.backend.data.DataFactoryService import DataFactoryService
    from snapred.backend.error.ContinueWarning import ContinueWarning
    from snapred.backend.recipe.ReductionRecipe import ReductionRecipe
    from snapred.backend.service.ReductionService import ReductionService
    from snapred.backend.dao.indexing.Versioning import Version, VersionState
    from snapred.meta.mantid.WorkspaceNameGenerator import WorkspaceNameGenerator as wng
    from snapred.meta.Config import Config
    from rich import print as printRich

    from mantid import config

    if verbose:
        config.setLogLevel(5, quiet=True)
    else:
        config.setLogLevel(0, quiet=True)

    print("SNAPBlue: gathering reduction ingredients...\n")
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # load reduction params from default yml with option to override 
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    #TODO: update default to final shared repo path

    if YMLOverride == 'none':
        defaultYML = "/SNS/SNAP/shared/Malcolm/code/SNAPBlue/defaultRedConfig.yml" #this will live in repo
    else:
        defaultYML = YMLOverride

    blueGlob = globalParams(defaultYML)

    #set global parameters
    useLiteMode=blueGlob.useLiteMode
    pixelMasks = blueGlob.pixelMasks
    keepUnfocussed = blueGlob.keepUnfocussed
    convertUnitsTo = blueGlob.convertUnitsTo

    #process continue flags
    continueFlags = ContinueWarning.Type.UNSET #by default do not continue

    if continueNoVan:
        artificialNormalizationIngredients = ArtificialNormalizationIngredients(
        peakWindowClippingSize = Config["constants.ArtificialNormalization.peakWindowClippingSize"],
        smoothingParameter=blueGlob.AN_smoothingParameter,
        decreaseParameter=blueGlob.AN_decreaseParameter,
        lss=blueGlob.AN_lss
        )
        continueFlags = ContinueWarning.Type.MISSING_NORMALIZATION
        
    else:
        artificialNormalizationIngredients = None

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # process input arguments
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    runNumber = str(runNumber)
    SEEFolder = f'{Config["instrument.calibration.home"]}/sampleEnvironmentDefinitions'

    if sampleEnv != 'none':
        seeDict = loadSEE(sampleEnv,SEEFolder)

        if seeDict["masks"]["maskExists"] and (seeDict["masks"]["maskType"]=="static"):
            # TODO: need to separately manage lite versus non lite masks
            # TODO: mantid can't load lite masks ... need to use SNAPRed
            pass

    if pixelMaskIndex != 'none':
        #check that provided value is a list convert if it isn't
        if type(pixelMaskIndex) is not list:
            pixelMaskIndex = [pixelMaskIndex]

        #check that all requested masks actually exist
        for maskIndex in pixelMaskIndex:
            if maskIndex == 0: #account for weird mantid indexing by getting rid of zero 
                maskName = (wng.reductionUserPixelMask().numberTag(1)).build()
            else:
                maskName = (wng.reductionUserPixelMask().numberTag(maskIndex)).build()

            if maskName not in mtd.getObjectNames():
                print(f"ERROR: you requested mask workspace {maskName} but this doesn\'t exist")
                assert False
            pixelMasks.append(maskName)
    
    reductionService = ReductionService()
    timestamp = reductionService.getUniqueTimestamp()

    reductionRequest = ReductionRequest(
        runNumber=runNumber,
        useLiteMode=useLiteMode,
        timestamp=timestamp,
        continueFlags=continueFlags,
        pixelMasks=pixelMasks,
        keepUnfocused=keepUnfocussed,
        convertUnitsTo=convertUnitsTo,
        artificialNormalizationIngredients=artificialNormalizationIngredients
    )

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    #  Load the supporting data (e.g. default pixel groups etc.)
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    reductionService.validateReduction(reductionRequest)

    # 1. load grouping workspaces from the state folder  TODO: how to init state?
    groupings = reductionService.fetchReductionGroupings(reductionRequest)
    reductionRequest.focusGroups = groupings["focusGroups"]
    # 2. Load Calibration (error out if it doesnt exist, comment out if continue anyway)
    # 3. Load Normalization (error out if it doesnt exist, comment out if continue anyway)
    # 3. Load the run data (lite or native)  
    groceries = reductionService.fetchReductionGroceries(reductionRequest)
    groceries["groupingWorkspaces"] = groupings["groupingWorkspaces"]

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    #  Load the metadata i.e. ingredients
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    # 1. load reduction ingredients
    ingredients = reductionService.prepReductionIngredients(reductionRequest, groceries.get("combinedPixelMask"))
    ingredients.artificialNormalizationIngredients = artificialNormalizationIngredients

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Determine calibration status and process this
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>


    dataFactoryService = DataFactoryService()
    calibrationPath = dataFactoryService.getCalibrationDataPath(
                runNumber, useLiteMode, VersionState.LATEST
            )
    # print(calibrationPath)
    calibrationRecord = dataFactoryService.getCalibrationRecord(
                runNumber, useLiteMode, VersionState.LATEST
            )
    
    if calibrationRecord.version == 0 and not continueNoDifcal:
        print("""         
                 
          - WARNING: NO DIFFRACTION CALIBRATION FOUND. TO PROCEED EITHER:
              1. RUN A DIFFRACTION CALIBRATION OR 
              2. SET "continueNoDifCal = True" TO PROCEED WITH DEFAULT GEOMETRY

            """)
        assert False

    # print(calibrationRecord.version)
    normalizationPath = dataFactoryService.getNormalizationDataPath(
                runNumber, useLiteMode, VersionState.LATEST
            )
    # print(normalizationPath)
    normalizationRecord = dataFactoryService.getNormalizationRecord(
                runNumber, useLiteMode, VersionState.LATEST
            )
    
    if type(normalizationRecord) == None:
        print("""         
                 
          - WARNING: NO VANADIUM FOUND. TO PROCEED EITHER: 
              1. RUN A VANADIUM CALIBRATION OR 
              2. SET "continueNoVan = True" TO USE ARTIFICIAL NORMALISATION

            """)
        
    
    # print(normalizationRecord.version)
    stateID = dataFactoryService.constructStateId(runNumber)


    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Pretty print useful information regarding reduction status
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> 

    allPixelGroups = []
    for ingredient in ingredients:   
        if ingredient[0] == "pixelGroups":
            for item in ingredient[1]:
                allPixelGroups.append(item.focusGroup.name)

    print(f"""
        SNAPRed:

            - Run Number: {ingredients.runNumber}

            - state: 
                - ID: {stateID[0]},
                - definition: {stateID[1]}

            - Pixel Groups to process: {allPixelGroups}

        """)
    
    if calibrationRecord.version==0 and continueNoDifcal:
        print("""

          - WARNING: DIAGNOSTIC MODE! DEFAULT GEOMETRY USED.

              """)
    else:
        print(f"""
          Calibration Status:
            - Diffraction Calibration:
                - .h5 path: {calibrationPath}
                - .h5 version: {calibrationRecord.version}

    """)

    if continueNoVan:
        print("""         
                 
          - WARNING: DIAGNOSTIC MODE! VANADIUM CORRECTION NOT USED
            DATA WILL BE ARTIFICIALLY NORMALISED BY DIVISION BY BACKGROUND.

            """)
    else:
        print(f"""            
                - Normalisation Calibration:
                    - raw vanadium path: {normalizationPath}
                    - raw vanadium version: {normalizationRecord.version}

            """)


    #optional arguments provided...

    if sampleEnv != 'none':
        print(f"""          
            Sample environment was specified.

                - name: {seeDict["name"]}
                - id: {seeDict["id"]}
                - type: {seeDict["type"]}
                - mask: {seeDict["masks"]["maskFilenameList"]} NOT YET IMPLEMENTED
            
            """)

    if pixelMasks != 'none' or []:
        print(f"""
            Mask workspace(s) specified:
        """)
        for mask in pixelMasks:
            print(f"""
                {mask}
                  """)

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Execute reduction here
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    data = ReductionRecipe().cook(ingredients, groceries)
    record = reductionService._createReductionRecord(reductionRequest, ingredients, data["outputs"])

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    #  Save the data
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    saveReductionRequest = ReductionExportRequest(
        record=record
    )

    reductionService.saveReduction(saveReductionRequest)

    #return logging to normal
    config.setLogLevel(3, quiet=True)


    print(f"""
        Reduction COMPLETE

            - Run Number: {ingredients.runNumber}

            - state: 
                - ID: {stateID[0]},
                - definition: {stateID[1]}

            - Pixel Groups to process: {allPixelGroups}

        """)
    
    if calibrationRecord.version==0 and continueNoDifcal:
        print("""
          - WARNING: DIAGNOSTIC MODE! DEFAULT GEOMETRY USED TO CONVERT UNITS.
              """)
    else:
        print(f"""
          Calibration Status:
            - Diffraction Calibration:
                - .h5 path: {calibrationPath}
                - .h5 version: {calibrationRecord.version}

    """)

    if continueNoVan:
        print("""         
          - WARNING: DIAGNOSTIC MODE! VANADIUM CORRECTION NOT USED
            DATA WILL BE ARTIFICIALLY NORMALISED USING DIVISION BY BACKGROUND
            """)
    else:
        print(f"""            
            - Normalisation Calibration:
                - raw vanadium path: {normalizationPath}
                - raw vanadium version: {normalizationRecord.version}

            """)

    #optional arguments provided...

    if sampleEnv != 'none':
        print(f"""          
            Sample environment was specified.

                - name: {seeDict["name"]}
                - id: {seeDict["id"]}
                - type: {seeDict["type"]}
                - mask: {seeDict["masks"]["maskFilenameList"]} NOT YET IMPLEMENTED
            
            """)

    if pixelMasks != 'none' or []:
        print(f"""
            Mask workspace(s) specified:
        """)
        for mask in pixelMasks:
            print(f"""
                {mask}
                  """)

