from common.configuration import paths, Configuration

threshold_occupancy = 0.9

deletion_per_iteration = 50

reco_max_age = 90. # number of days to keep /RECO* datasets
max_nonusage = 400. # threshold for global usage rank

routine_exceptions = [
    ('Keep', '*', '/HLTPhysics/CMSSW_7_4_14-2015_10_20_newconditions0_74X_dataRun2_HLTValidation_Candidate_2015_10_12_10_41_09-v1/RECO'),
    ('Keep', '*', '/HLTPhysics/CMSSW_7_4_14-2015_10_20_reference_74X_dataRun2_HLT_v2-v1/RECO'),
    ('Keep', '*', '/ZeroBias*/Run2015A-PromptReco-v1/RECO'),
    ('Keep', '*', '/*TOTEM*/*Run2015D*/RECO')
]
