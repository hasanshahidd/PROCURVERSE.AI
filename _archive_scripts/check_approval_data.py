"""
Check approval system data to debug the 50% confidence issue
"""
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from backend.services import hybrid_query

def check_pending_approvals():
    print("\n=== PENDING APPROVALS TABLE ===")
    conn = hybrid_query.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT approval_id, agent_name, request_type, confidence_score, 
               reasoning, status, created_at
        FROM pending_approvals
        ORDER BY created_at DESC
        LIMIT 20
    """)
    
    results = cursor.fetchall()
    print(f"\nTotal pending approvals: {len(results)}")
    
    for row in results:
        print(f"\n{row['approval_id']}")
        print(f"  Agent: {row['agent_name']}")
        print(f"  Confidence: {row['confidence_score']:.2%}")
        print(f"  Status: {row['status']}")
        print(f"  Reasoning: {row['reasoning'][:100]}...")
    
    # Check distribution of confidence scores
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN confidence_score < 0.5 THEN 1 END) as below_50,
            COUNT(CASE WHEN confidence_score = 0.5 THEN 1 END) as exactly_50,
            COUNT(CASE WHEN confidence_score > 0.5 AND confidence_score < 0.6 THEN 1 END) as between_50_60,
            AVG(confidence_score) as avg_confidence
        FROM pending_approvals
        WHERE status = 'pending'
    """)
    
    stats = cursor.fetchone()
    print(f"\n=== CONFIDENCE SCORE STATS ===")
    print(f"Total pending: {stats['total']}")
    print(f"Below 50%: {stats['below_50']}")
    print(f"Exactly 50%: {stats['exactly_50']}")
    print(f"Between 50-60%: {stats['between_50_60']}")
    print(f"Average confidence: {stats['avg_confidence']:.2%}")
    
    cursor.close()
    conn.close()


def check_pr_workflows():
    print("\n\n=== PR APPROVAL WORKFLOWS ===")
    conn = hybrid_query.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT pr_number, department, total_amount, current_approval_level,
               workflow_status, created_at
        FROM pr_approval_workflows
        ORDER BY created_at DESC
        LIMIT 10
    """)
    
    workflows = cursor.fetchall()
    print(f"\nTotal workflows: {len(workflows)}")
    
    for w in workflows:
        print(f"\n{w['pr_number']} - {w['department']}")
        print(f"  Amount: ${w['total_amount']:,.2f}")
        print(f"  Current Level: {w['current_approval_level']}")
        print(f"  Status: {w['workflow_status']}")
    
    cursor.close()
    conn.close()


def check_pr_steps():
    print("\n\n=== PR APPROVAL STEPS (PENDING) ===")
    conn = hybrid_query.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT s.pr_number, s.approval_level, s.approver_email, s.approver_name,
               s.status, w.total_amount, w.department
        FROM pr_approval_steps s
        JOIN pr_approval_workflows w ON s.pr_number = w.pr_number
        WHERE s.status = 'pending'
        ORDER BY s.pr_number, s.approval_level
        LIMIT 20
    """)
    
    steps = cursor.fetchall()
    print(f"\nTotal pending steps: {len(steps)}")
    
    # Group by PR
    current_pr = None
    for step in steps:
        if step['pr_number'] != current_pr:
            current_pr = step['pr_number']
            print(f"\n{step['pr_number']} ({step['department']}) - ${step['total_amount']:,.2f}")
        
        level_name = {1: "Manager", 2: "Director", 3: "VP/CFO"}.get(step['approval_level'], "Unknown")
        print(f"  Level {step['approval_level']} ({level_name}): {step['approver_name']} ({step['approver_email']})")
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    print("=" * 80)
    print("APPROVAL SYSTEM DATA CHECK")
    print("=" * 80)
    
    check_pending_approvals()
    check_pr_workflows()
    check_pr_steps()
    
    print("\n" + "=" * 80)
    print("END OF REPORT")
    print("=" * 80)
