# Cost Janitor Report

**Scan time:** 2026-05-25T12:41:55Z  
**Account:** `000000000000`  
**Region:** `us-east-1`  

## Summary

| Metric | Value |
|--------|-------|
| Total orphans found | **9** |
| Estimated monthly waste | **$30.60** |

## Findings

| Resource ID | Type | Reason | Age (days) | Est. Cost/mo | Safe to Delete |
|-------------|------|--------|-----------|-------------|----------------|
| `vol-a5b6f1c5` | ebs_volume | unattached | 0 | $1.60 | Yes |
| `vol-8c0f6d75` | ebs_volume | unattached|missing_tags:Project,Environment,Owner | 0 | $5.00 | No |
| `vol-e6749f89` | ebs_volume | unattached|missing_tags:Project,Environment,Owner | 0 | $5.00 | No |
| `vol-707ab632` | ebs_volume | unattached|missing_tags:Project,Environment,Owner | 0 | $5.00 | No |
| `i-a0042c130e55d3950` | ec2_instance | stopped>14d|missing_tags:Project,Environment,Owner | 15 | $1.60 | No |
| `i-cd96df535f4aec325` | ec2_instance | stopped>14d|missing_tags:Project,Environment,Owner | 15 | $1.60 | No |
| `eipalloc-d0815a1f` | elastic_ip | unassociated|missing_tags:Project,Environment,Owner | 0 | $3.60 | No |
| `eipalloc-16654873` | elastic_ip | unassociated|missing_tags:Project,Environment,Owner | 0 | $3.60 | No |
| `eipalloc-e1b24434` | elastic_ip | unassociated|missing_tags:Project,Environment,Owner | 0 | $3.60 | No |

---
> Resources marked are not safe to auto-delete.
> They may be missing tags, carry `Protected=true`, or are running instances.
> Review manually before taking action.
