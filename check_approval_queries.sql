"""
Quick SQL check for approval issues
Run directly with psql or via pgAdmin
"""

-- Check 1: How many pending approvals exist with what confidence scores?
SELECT 
    status,
    COUNT(*) as count,
    AVG(confidence_score) as avg_confidence,
    MIN(confidence_score) as min_confidence,
    MAX(confidence_score) as max_confidence
FROM pending_approvals
GROUP BY status;

-- Check 2: List all pending approvals showing confidence scores
SELECT 
    approval_id,
    agent_name,
    confidence_score,
    ROUND(confidence_score * 100, 0) || '%' as confidence_pct,
    status,
    created_at
FROM pending_approvals
WHERE status = 'pending'
ORDER BY created_at DESC
LIMIT 30;

-- Check 3: Check PR workflows - how many exist?
SELECT 
    workflow_status,
    COUNT(*) as count
FROM pr_approval_workflows
GROUP BY workflow_status;

-- Check 4: Check approval steps - who has how many pending?
SELECT 
    approver_email,
    approver_name,
    COUNT(*) as pending_count
FROM pr_approval_steps
WHERE status = 'pending'
GROUP BY approver_email, approver_name
ORDER BY pending_count DESC;

-- Check 5: All pending steps with details
SELECT 
    s.pr_number,
    w.department,
    w.total_amount,
    s.approval_level,
    s.approver_name,
    s.approver_email,
    s.status
FROM pr_approval_steps s
JOIN pr_approval_workflows w ON s.pr_number = w.pr_number
WHERE s.status = 'pending'
ORDER BY s.pr_number, s.approval_level;
