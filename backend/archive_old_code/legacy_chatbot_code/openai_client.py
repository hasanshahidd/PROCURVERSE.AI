import os
import re
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# MINIMAL SYSTEM PROMPT - Legacy table removed Feb 24, 2026
# System now uses ONLY:
# 1. Agentic system (BudgetVerificationAgent, ApprovalRoutingAgent, Orchestrator)
# 2. Odoo ERP (purchase orders, vendors, products)
# 3. Custom tables (approval_chains, budget_tracking, agent_actions, agent_decisions)
SYSTEM_PROMPT = """You are a helpful procurement assistant.

**Available Data Sources:**
1. **BudgetVerificationAgent** - Checks budget availability for departments
2. **ApprovalRoutingAgent** - Routes PRs through approval chains
3. **Odoo ERP** - Purchase orders, vendors, products (via API)
4. **Budget Tracking** - 4 departments (IT, Finance, Operations, Procurement) with CAPEX/OPEX budgets
5. **Approval Chains** - Multi-level approval workflows (Manager→Director→VP/CFO)

**For Budget/Approval Decisions:**
- "Can [dept] afford $X?" → Route to BudgetVerificationAgent
- "Who should approve $X?" → Route to ApprovalRoutingAgent
- "Show budget status" → Display from budget_tracking table

**Critical Budget Rules:**
- "Available budget" = allocated - spent - committed (what's LEFT to spend)
- "Allocated budget" = total budget for fiscal year
- NEVER confuse these! If available=$1.1M, you CANNOT afford $2M

**For General Questions:**
- Greetings: Respond conversationally
- Help requests: Explain what you can do
- Odoo data: Suggest using dashboard or API endpoints

Respond in the user's language. Format responses as JSON:
{
  "sql": null,
  "explanation": "Your conversational response"
}
"""

def split_questions(message: str) -> list[str]:
    """Split message into individual questions if multiple questions detected."""
    # Split by newlines first
    lines = [line.strip() for line in message.split('\n') if line.strip()]
    
    # If we have multiple lines that look like questions, treat each as separate
    if len(lines) > 1:
        questions = []
        for line in lines:
            # Check if line looks like a question (ends with ?, contains question words, or is a command)
            if line.endswith('?') or any(word in line.lower() for word in ['show', 'list', 'what', 'how', 'which', 'get', 'find', 'count']):
                questions.append(line)
        
        # If we found multiple question-like lines, return them
        if len(questions) > 1:
            return questions
    
    # Otherwise return as single question
    return [message]

def detect_multi_part_query(message: str) -> bool:
    """Detect if user is EXPLICITLY asking for multiple separate tables/analyses."""
    # Only trigger if user EXPLICITLY mentions second table or table 2
    strict_indicators = [
        "second table", "2nd table",
        "in second table", "in table 2",
        "table 1 and table 2",
        "first table and second table"
    ]
    message_lower = message.lower()
    
    # Must explicitly mention second/2nd table
    return any(indicator in message_lower for indicator in strict_indicators)

def generate_followup_query(original_message: str, first_response: str, language: str = "en") -> dict:
    """Generate the second query for multi-part requests."""
    try:
        prompt = f"""Based on the user's original question and the first query response, generate the SECOND/ADDITIONAL query they requested.

Original question: {original_message}
First query completed: {first_response}

User asked for multiple analyses. Generate the SECOND query now.

Common patterns:
- "by department AND by month" → First: GROUP BY department, Second: GROUP BY month
- "target vs actual workflow" → Query all workflow stages with *_pd and *_ad columns
- "first table... second table..." → Generate the second table query

Return JSON:
{{
  "sql": "SELECT ... for second analysis",
  "explanation": "This provides the second table/analysis requested"
}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=800
        )
        
        import json
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        return {"sql": None, "explanation": f"Could not generate follow-up query: {str(e)}"}

def process_chat(message: str, language: str = "en", history: list = None) -> dict:
    try:
        # Build conversation messages with history for context
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add conversation history if provided (last 5 messages for context)
        if history:
            # Include last 5 exchanges to maintain context while limiting token usage
            recent_history = history[-10:] if len(history) > 10 else history
            for msg in recent_history:
                role = msg.get("role")
                content = msg.get("content")
                if role and content:
                    messages.append({"role": role, "content": content})
        
        # Add current user message
        messages.append({"role": "user", "content": f"User's language preference: {language}\n\nUser message: {message}"})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=1000
        )
        
        content = response.choices[0].message.content
        import json
        result = json.loads(content)
        
        return {
            "sql": result.get("sql"),
            "explanation": result.get("explanation", "")
        }
    except Exception as e:
        return {
            "sql": None,
            "explanation": f"Error processing your request: {str(e)}"
        }

def generate_response(query_results: list, original_question: str, language: str = "en") -> str:
    if not query_results:
        # Detect if question is in Arabic or English
        is_arabic = language == "ar" or any(ord(c) >= 0x0600 and ord(c) <= 0x06FF for c in original_question)
        
        # More helpful message for no data - in user's language
        if "2023" in original_question or "2026" in original_question or "٢٠٢٣" in original_question or "٢٠٢٦" in original_question:
            if is_arabic:
                return "لا توجد بيانات. قاعدة البيانات تحتوي على سجلات للأعوام 2024 و 2025 فقط."
            return "No data found. The database contains records for years 2024 and 2025 only."
        elif ("500" in original_question or "500k" in original_question.lower()) and ("budget" in original_question.lower() or "cost" in original_question.lower() or "الميزانية" in original_question):
            if is_arabic:
                return "لا توجد طلبات شراء بميزانية تزيد عن 500 ألف دولار. أعلى ميزانية في البيانات هي 499 ألف دولار. حاول البحث عن طلبات تزيد عن 400 ألف دولار (15 طلبًا) أو 450 ألف دولار (7 طلبات) بدلاً من ذلك."
            return "No PRs found with budget over $500K. The maximum budget in the data is $499K. Try searching for PRs over $400K (15 PRs) or $450K (7 PRs) instead."
        elif ("evaluation" in original_question.lower() or "under review" in original_question.lower() or "التقييم" in original_question or "المراجعة" in original_question) and ("30" in original_question):
            if is_arabic:
                return "لا توجد طلبات شراء في مرحلة التقييم لأكثر من 30 يومًا. الحد الأقصى في البيانات الحالية هو 30 يومًا. حاول البحث عن '> 25 يومًا' (11 طلبًا) أو '> 20 يومًا' (21 طلبًا) بدلاً من ذلك."
            return "No PRs found in evaluation for more than 30 days. The maximum duration in current data is 30 days. Try searching for '> 25 days' (11 PRs) or '> 20 days' (21 PRs) instead."
        elif "John Smith" in original_question or "XYZ" in original_question:
            if is_arabic:
                return "لم يتم العثور على سجلات بهذا الاسم أو رقم الطلب. يرجى التحقق من الاسم/الرقم الدقيق أو محاولة تصفح السجلات المتاحة."
            return "No records found with that specific name or PR number. Please check the exact name/number or try browsing available records."
        elif "my department" in original_question.lower() or "قسمي" in original_question or "إدارتي" in original_question:
            if is_arabic:
                return "يرجى تحديد اسم القسم (مثل: تقنية المعلومات، المالية، الموارد البشرية، المبيعات، التسويق، البحث والتطوير، العمليات، القانونية، المشتريات، الهندسة)."
            return "Please specify your department name (e.g., IT, Finance, HR, Sales, Marketing, R&D, Operations, Legal, Procurement, Engineering) to see results."
        elif "rating" in original_question.lower() and (">" in original_question or "above" in original_question or "greater" in original_question):
            if is_arabic:
                return "تقييمات الموردين هي درجات حرفية (A+, A, B+, B, C+, C)، وليست رقمية. استخدم استعلامات مثل 'التقييم = A+' للموردين الأعلى تقييمًا."
            return "Supplier ratings are letter grades (A+, A, B+, B, C+, C), not numeric. Use queries like 'rating IN (\"A+\", \"A\")' for top-rated suppliers or 'rating IN (\"C\", \"C+\")' for lower-rated ones."
        else:
            if is_arabic:
                return "لا توجد سجلات تطابق معايير البحث. حاول تعديل الفلاتر أو التحقق من نطاقات البيانات المتاحة (الأعوام 2024-2025)."
            return "No records match your query criteria. Try adjusting your filters or checking available data ranges (years 2024-2025)."
    
    try:
        # Send all results to AI for accurate analysis (up to 100 records for display)
        display_limit = 100
        all_data_str = str(query_results[:display_limit])
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""You are a data analyst providing ACCURATE, CLEAR responses.

CRITICAL BUDGET RULES:
- "Available budget" = What's LEFT TO SPEND (allocated - spent - committed)
- "Allocated budget" = TOTAL budget for the year
- NEVER confuse these two!
- If someone asks "can afford $X", they need $X in AVAILABLE budget, NOT just allocated
- Example: If available=$1.1M, they CANNOT afford $2M (even if allocated=$2M)

STRICT FORMAT RULES:
1. **## Main Heading** (use ## for main heading - BOLD and prominent)
2. Brief summary (1 sentence only)
3. **Key Insights:** (2-3 bullets maximum)
   - Bullet point 1
   - Bullet point 2
4. **Table** (ONE table only)

HEADING FORMAT - CRITICAL:
- Main heading: ## Heading Text (use ## markdown)
- Section headers: **Section Name:** (use bold)
- All headings MUST be bold and prominent

OUTPUT LIMITS (STRICTLY ENFORCED):
- Maximum 15 rows per table (HARD LIMIT - DO NOT EXCEED)
- If dataset has >15 rows, show first 15 and state "(Showing 15 of X total)"
- ONE table only (not multiple tables)
- Keep total response under 1200 tokens

CRITICAL:
- COUNT ACCURATELY from the data provided
- Use proper currency format: $1,234.56
- State exact total count
- NO approximations or guesses
- Respond in {language}
- Format numbers with commas and proper alignment

EXAMPLE FORMAT:
## Budget Analysis Report

Found 45 projects matching criteria.

**Key Insights:**
- Point 1
- Point 2

**Table:**
| Department | Count | Budget |
|------------|-------|--------|

(Showing 15 of 45 total)"""},
                {"role": "user", "content": f"Question: {original_question}\n\nData: {all_data_str}\n\nTotal records: {len(query_results)}\n\nProvide response with bold headings. MAXIMUM 15 ROWS IN TABLE."}
            ],
            temperature=0.1,
            max_tokens=1200
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"Found {len(query_results)} records. Error generating summary: {str(e)}"

def generate_multi_table_response(all_datasets: list, original_question: str, language: str = "en") -> str:
    """Generate response for multi-part queries with multiple datasets."""
    try:
        # Prepare data summary for each dataset
        datasets_info = []
        for i, dataset in enumerate(all_datasets, 1):
            if dataset:
                dataset_str = str(dataset[:50])  # First 50 records per dataset
                datasets_info.append(f"Dataset {i}: {len(dataset)} records\n{dataset_str}")
            else:
                datasets_info.append(f"Dataset {i}: No data")
        
        combined_data_str = "\n\n---\n\n".join(datasets_info)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""You are a data analyst providing ACCURATE, CLEAR responses with MULTIPLE TABLES.

The user requested multiple analyses. You have {len(all_datasets)} datasets to present.

STRICT FORMAT:
1. **## Main Heading** (use ## markdown for main heading)
2. Brief summary (1 sentence only)
3. **Key Insights:** (2 bullets maximum)
   - Bullet 1
   - Bullet 2

4. **### TABLE 1: [First Analysis Name]** (use ### for table headings)
   [First table - maximum 15 rows]
   (Showing X of Y total if >15)
   
5. **### TABLE 2: [Second Analysis Name]**
   [Second table - maximum 15 rows]
   (Showing X of Y total if >15)

HEADING FORMAT - CRITICAL:
- Main heading: ## Main Title
- Table headings: ### TABLE 1: Description
- Section headers: **Header:**
- ALL headings must be BOLD and prominent

OUTPUT LIMITS (STRICTLY ENFORCED):
- Maximum 15 rows per table (HARD LIMIT - DO NOT EXCEED)
- If >15 rows, show first 15 and add: "(Showing 15 of X total)"
- Maximum 2 tables total
- Keep response under 1500 tokens

CRITICAL:
- Create SEPARATE, CLEARLY LABELED tables for each dataset
- Use proper markdown table formatting with | separators
- Include totals/summaries where applicable
- Respond in {language}
- Format numbers with commas: 1,234

For workflow comparisons:
| Stage Name | Target Days | Actual Days | Variance | Status |

For time-series: Include chronological ordering."""},
                {"role": "user", "content": f"Question: {original_question}\n\n{combined_data_str}\n\nCreate separate tables. MAXIMUM 15 ROWS PER TABLE."}
            ],
            temperature=0.1,
            max_tokens=1500
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating multi-table response: {str(e)}"

def generate_insights_and_recommendations(data: list, original_question: str, language: str = "en") -> str:
    """Generate strategic insights and recommendations based on query results."""
    if not data or len(data) == 0:
        return ""  # No insights for empty data
    
    # Skip insights for very simple queries (like single PR lookups)
    if len(data) == 1:
        return ""
    
    try:
        # Analyze data to generate insights
        data_summary = str(data[:100])  # Sample of data for analysis
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""You are a strategic procurement analyst providing ACTIONABLE INSIGHTS.

Analyze the query results and provide:
1. **Pattern Detection**: Identify trends, anomalies, or risks
2. **Strategic Alerts**: Flag critical issues requiring attention
3. **Actionable Recommendations**: Suggest specific next steps

FORMAT:
---

### 🔍 **AI Insights & Recommendations**

**Patterns Detected:**
- [Pattern 1 with specific numbers/percentages]
- [Pattern 2 with specific data points]

**⚠️ Alerts:**
- [Critical issue with specific PR numbers or metrics]

**💡 Recommendations:**
- [Actionable step 1 with specific details]
- [Actionable step 2 with specific details]

RULES:
- Use SPECIFIC numbers and percentages (e.g., "23% of high-risk PRs")
- Include PR numbers when relevant (e.g., "PR-2024-0045")
- Focus on ACTIONABLE insights (not just observations)
- Keep VERY concise (2-3 bullets TOTAL, not per section)
- Maximum 2 bullets per section
- Use {language} language
- If no significant patterns, return empty string

EXAMPLES:
- "23% of high-risk PRs (12 out of 52) are stuck in evaluation for >20 days"
- "IT Department has 45% SLA breach rate - highest across all departments"
- "Consider expediting PR-2024-0045 (45 days overdue, $450K budget)"
"""},
                {"role": "user", "content": f"Question: {original_question}\n\nData ({len(data)} records): {data_summary}\n\nAnalyze and provide strategic insights. Keep very brief (2-3 bullets total)."}
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        insights = response.choices[0].message.content.strip()
        
        # Only return if we got meaningful insights
        if insights and len(insights) > 50 and "no significant" not in insights.lower():
            return "\n\n" + insights
        return ""
        
    except Exception as e:
        print(f"Insights generation error: {e}")
        return ""  # Fail silently to not break main response

def validate_sql(sql: str) -> bool:
    if not sql:
        return False
    
    normalized = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    normalized = re.sub(r'/\*.*?\*/', '', normalized, flags=re.DOTALL)
    normalized = ' '.join(normalized.split()).lower().strip()
    
    if not normalized.startswith("select"):
        return False
    
    forbidden = [
        "drop", "delete", "update", "insert", "alter", "truncate",
        "create", "grant", "revoke", "execute", "exec", "call",
        "copy", "pg_", "information_schema", "pg_catalog"
    ]
    for keyword in forbidden:
        if keyword in normalized:
            return False
    
    if ";" in normalized and normalized.index(";") < len(normalized) - 1:
        return False
    
    return True

def fix_failed_query(failed_sql: str, error_message: str, original_question: str, language: str = "en") -> dict:
    """Try to fix a failed SQL query based on the error message."""
    try:
        fix_prompt = f"""The following SQL query failed with an error. Please fix it.

Original question: {original_question}
Failed SQL: {failed_sql}
Error: {error_message}

Common fixes:
- If "must appear in the GROUP BY clause": Add all non-aggregated columns to GROUP BY
- If "column does not exist": Check column names in the schema
- If "cannot cast": Remove CAST operations on TEXT columns like supplier_rating or risk
- If date comparison fails: Use CAST(date AS DATE) for date column

Generate the corrected SQL query. Return JSON format:
{{
  "sql": "corrected SELECT query",
  "explanation": "What was fixed"
}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": fix_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500
        )
        
        import json
        result = json.loads(response.choices[0].message.content)
        return result
    except:
        return {"sql": None, "explanation": "Could not fix query"}

def generate_error_response(error_message: str, original_question: str, language: str = "en") -> str:
    """Generate a helpful error message for users."""
    error_lower = error_message.lower()
    
    # Common error patterns
    if "group by" in error_lower:
        return "I encountered an issue with data aggregation. Let me know if you'd like to see individual records instead of summaries, or try rephrasing your question."
    elif "column" in error_lower and "does not exist" in error_lower:
        return "I tried to access a column that doesn't exist in the database. Please rephrase your question or check the available data fields."
    elif "cast" in error_lower or "invalid input" in error_lower:
        return "I encountered a data type mismatch. This might be due to comparing text values as numbers. Please rephrase your question."
    elif "syntax error" in error_lower:
        return "I generated an invalid query. Please try rephrasing your question in a different way."
    else:
        return f"I encountered an error processing your request. Please try rephrasing your question or breaking it into smaller parts. If the issue persists, try asking about specific aspects like 'Show me IT department PRs' or 'What's the total budget for 2024?'"

def generate_query_suggestions(partial_input: str, language: str = "en", conversation_context: list = None) -> list:
    """Generate smart query completion suggestions based on partial user input."""
    try:
        # Build context from conversation
        context_str = ""
        if conversation_context and len(conversation_context) > 0:
            recent = conversation_context[-3:] if len(conversation_context) > 3 else conversation_context
            context_str = f"\n\nRecent conversation:\n" + "\n".join([f"- {q}" for q in recent])
        
        prompt = f"""You are an autocomplete assistant. The user is typing a query about procurement data. Complete what they're typing with relevant suggestions based on the actual data available.

DATABASE SCHEMA:
- pr_number, requester_name, department
- budget_amount (range: $10K-$499K)
- risk_level (Low, Medium, High, Critical, None)
- current_status (Approved, Cancelled, Completed, In Progress, On Hold, Pending, Under Review)
- escalation_flag (48-hour escalation, CEO approval, CFO approval)
- sla_difference (days delayed/ahead)
- evaluation_stage, approval_date, created_at

AVAILABLE DATA:
- Departments: IT, Finance, HR, Sales, Marketing, R&D, Operations, Legal, Procurement, Engineering
- 500 records from 2024-2025
- Budget range: $10,000 to $499,000
- Risk levels tracked per PR
- SLA tracking with delays

User typed: "{partial_input}"{context_str}

TASK: Generate 5 autocomplete suggestions that:
1. START with what the user typed (or close variation)
2. Complete their query naturally based on ACTUAL database fields
3. Are specific and actionable (e.g., "show PRs over $300K", "which departments have high risk")
4. Use real values from the database (departments, statuses, risk levels mentioned above)
5. Language: {language}

Examples of GOOD autocomplete:
- User types "show" → "show all high-risk PRs", "show IT department budget", "show pending approvals"
- User types "which" → "which PRs exceed $400K", "which departments have critical risk", "which PRs need CEO approval"
- User types "how many" → "how many PRs are pending", "how many high-risk projects", "how many delayed PRs"

Return ONLY valid JSON object with "suggestions" array:
{{"suggestions": ["completion 1", "completion 2", "completion 3", "completion 4", "completion 5"]}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a query suggestion assistant. Return only a valid JSON array of 5 string suggestions."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=300
        )
        
        import json
        result = json.loads(response.choices[0].message.content)
        
        # Handle different response formats
        if isinstance(result, dict):
            suggestions = result.get("suggestions", [])
        elif isinstance(result, list):
            suggestions = result
        else:
            suggestions = []
        
        # Filter and limit to 5
        suggestions = [s.strip() for s in suggestions if isinstance(s, str) and len(s.strip()) > 0]
        return suggestions[:5]
        
    except Exception as e:
        print(f"Suggestion generation error: {e}")
        # Return empty list on error
        return []
