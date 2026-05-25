# ── Pricing Constants ─────────────────────────────────────────────────────────
EBS_COST_PER_GB_MONTH = {
    "gp2": 0.10,   
    "gp3": 0.08,   
    "io1": 0.125,  
    "io2": 0.125,  
    "st1": 0.045,  
    "sc1": 0.015,  
    "standard": 0.05,  
}
EBS_DEFAULT_COST_PER_GB_MONTH = 0.08  


EC2_STOPPED_COST_PER_MONTH = {
    "default_root_gb": 20,
}

EIP_IDLE_COST_PER_MONTH = 3.60 


REQUIRED_TAGS = ["Project", "Environment", "Owner"]


PROTECTED_TAG_KEY = "Protected"
PROTECTED_TAG_VALUE = "true"  


DEFAULT_STOPPED_DAYS_THRESHOLD = 14