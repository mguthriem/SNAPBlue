import sys
import importlib
sys.path.append("/SNS/SNAP/shared/Malcolm/code/SNAPBlue")
import blueUtils as blue
importlib.reload(blue)
from mantid import config
config.setLogLevel(0, quiet=True)

#to do a simple reduction of run 61991

#example run where difcal exists but vanadium doesn't
# blue.reduceSNAP(58882,
#    sampleEnv="PE_001", # currently this loads parameters but doesn't do anything
#    continueNoVan=True
#    ) 
    

# #example run with full calibration is 61991
# blue.reduceSNAP(61991,
#     sampleEnv="PE_001", # currently this loads parameters but doesn't do anything
#     continueNoVan=False
#     )

#example run where state exists but has no difcal
blue.reduceSNAP(63424,
    sampleEnv="PE_001", # currently this loads parameters but doesn't do anything
    continueNoVan=True,
    continueNoDifcal=True
    )
    
#if state doesn't exist, SNAPRed will fail