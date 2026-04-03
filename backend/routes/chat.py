from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from openai import OpenAI
import json
import asyncio
import os
import psycopg2
from psycopg2.extras import RealDictCursor

from backend.services import conversational_handler, translation_service, hybrid_query, query_router
from backend.services.db_pool import get_db_connection, return_db_connection
from backend.services.rbac import require_auth

router = APIRouter()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    message: str
    language: str = "en"
    history: List[Dict[str, Any]] = []

class ChatResponse(BaseModel):
    response: str
    sql: Optional[str] = None
    data: Optional[list] = None
    chartData: Optional[list] = None  # Prepared data for charting

class QueryRequest(BaseModel):
    sql: str

class SuggestionRequest(BaseModel):
    partial_input: str
    language: str = "en"
    conversation_context: List[str] = []

class SuggestionResponse(BaseModel):
    suggestions: List[str]


def execute_custom_select_query(sql: str) -> list:
    """Execute validated SELECT query against known procurement tables.
    Enforces a 5-second statement timeout to prevent long-running abuse."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SET LOCAL statement_timeout = '5000'")
        cursor.execute(sql)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        return_db_connection(conn)

@router.get("/stats")
async def get_stats(current_user: dict = Depends(require_auth())):
    print("\n" + "="*80)
    print("[STATS ENDPOINT] 📊 System stats requested")
    print("="*80)
    try:
        print("[STATS] 🔍 Querying system statistics...")
        stats = hybrid_query.get_system_stats()
        print(f"[STATS] ✅ Retrieved: Odoo ({stats.get('odoo', {}).get('purchase_orders', 0)} POs), Agentic ({stats.get('agentic_tables', {}).get('agent_actions', 0)} actions)")
        print("="*80 + "\n")
        return stats
    except Exception as e:
        print(f"[STATS] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[STATS] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat")
async def chat(request: ChatRequest, current_user: dict = Depends(require_auth())):
    """
    Hybrid conversational endpoint - works with Odoo + custom agentic tables
    """
    print("\n" + "="*80)
    print("[CHAT ENDPOINT] 💬 New chat request received")
    print("="*80)
    try:
        print(f"[CHAT] 📥 Request details:")
        print(f"[CHAT]   - Message: {request.message[:100]}{'...' if len(request.message) > 100 else ''}")
        print(f"[CHAT]   - Language: {request.language}")
        print(f"[CHAT]   - History length: {len(request.history)}")
        
        # ============================================
        # STEP 1: Translate user input to English
        # ============================================
        original_message = request.message
        user_language = request.language
        
        if translation_service.is_translation_needed(user_language):
            print(f"[CHAT] 🌐 Translation required: {user_language} → en")
            request.message = translation_service.translate_to_english(
                request.message, 
                user_language
            )
            print(f"[CHAT] ✅ Translated: {original_message[:50]} → {request.message[:50]}")
        else:
            print(f"[CHAT] ⏭️  No translation needed (language: {user_language})")
        
        # ============================================
        # STEP 2: Route query through unified query router
        # ============================================
        print(f"\n[CHAT ENDPOINT] 🔍 Routing query through unified query router...")
        print(f"[CHAT ENDPOINT] 📝 Message: '{request.message}'")
        print(f"[CHAT ENDPOINT] 🌍 User language: {user_language}")
        
        # Use unified router (handles general/odoo/agentic/multi-intent automatically)
        result = query_router.route_and_execute_query(request.message, language="en")
        
        data_list = result.get("data", [])
        explanation = result.get("explanation", "")
        source = result.get("source", "unknown")
        
        # Prepare chart data (limit to 15 records for performance)
        chart_data = data_list[:15] if len(data_list) > 0 else None
        
        # ============================================
        # STEP 3: Translate response back to user language
        # ============================================
        if translation_service.is_translation_needed(user_language):
            explanation = translation_service.translate_from_english(explanation, user_language)
        
        return ChatResponse(
            response=explanation,
            sql=None,  # No SQL for Odoo API calls
            data=data_list[:100],  # Limit for performance
            chartData=chart_data
        )
            
    except Exception as e:
        error_msg = f"Error processing query: {str(e)}"
        if translation_service.is_translation_needed(user_language):
            error_msg = translation_service.translate_from_english(error_msg, user_language)
        return ChatResponse(response=error_msg)


@router.post("/suggestions")
async def get_suggestions(request: SuggestionRequest, current_user: dict = Depends(require_auth())):
    """Generate smart query suggestions based on user's partial input"""
    try:
        if not request.partial_input or len(request.partial_input.strip()) < 3:
            return SuggestionResponse(suggestions=[])
        
        # Translate input to English if needed
        original_input = request.partial_input
        user_language = request.language
        
        if translation_service.is_translation_needed(user_language):
            request.partial_input = translation_service.translate_to_english(
                request.partial_input, user_language
            )
        
        # Generate suggestions using AI (in English)
        suggestions = conversational_handler.generate_query_suggestions(
            request.partial_input,
            "en",  # Always process in English
            request.conversation_context
        )
        
        # Translate suggestions back to user language
        if translation_service.is_translation_needed(user_language):
            translated_suggestions = []
            for suggestion in suggestions:
                translated_suggestion = translation_service.translate_from_english(
                    suggestion,
                    user_language
                )
                translated_suggestions.append(translated_suggestion)
            suggestions = translated_suggestions
        
        return SuggestionResponse(suggestions=suggestions)
    except Exception as e:
        # Don't fail hard on suggestions - just return empty
        print(f"Suggestion error: {e}")
        return SuggestionResponse(suggestions=[])

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, current_user: dict = Depends(require_auth())):
    """Streaming endpoint with hybrid query system (Odoo + custom tables)"""
    print("\n" + "="*80)
    print("[STREAM ENDPOINT] 🌐 SSE Stream request received")
    print("="*80)
    print(f"[STREAM] 📥 Message: '{request.message[:100]}{'...' if len(request.message) > 100 else ''}'")
    print(f"[STREAM] 🌍 Language: {request.language}")
    
    async def generate_stream():
        try:
            print(f"[STREAM] 🚀 Starting stream generation...")
            # ============================================
            # STEP 1: Translate input to English if needed
            # ============================================
            original_message = request.message
            user_language = request.language
            
            if translation_service.is_translation_needed(user_language):
                print(f"[STREAM] 🌐 Translating: {user_language} → en")
                request.message = translation_service.translate_to_english(
                    request.message, user_language
                )
                print(f"[STREAM] ✅ Translation complete")
            
            # Step 1: Analyzing query (0-25%)
            yield f"data: {json.dumps({'type': 'progress', 'step': 1, 'total': 4, 'status': 'active', 'message': 'Analyzing your question'})}\n\n"
            await asyncio.sleep(0.2)
            
            # Classify query type
            print(f"\n[STREAM ENDPOINT] 🔍 Processing: '{request.message}'")
            print(f"[STREAM ENDPOINT] 🌍 Language: {user_language}")
            
            classification = query_router.classify_query_intent(request.message)
            data_source = classification.get("data_source", "general")
            
            print(f"[STREAM ENDPOINT] Classified as: {data_source}")
            
            # Step 1 Complete
            yield f"data: {json.dumps({'type': 'progress', 'step': 1, 'total': 4, 'status': 'completed', 'message': 'Analyzing your question'})}\n\n"
            await asyncio.sleep(0.05)
            
            # Step 2: Get data
            data_list = []
            response_text = ""
            
            if data_source == "general":
                # Use conversational AI for greetings/general questions
                print(f"[STREAM ENDPOINT] → Using conversational AI")
                yield f"data: {json.dumps({'type': 'progress', 'step': 2, 'total': 4, 'status': 'active', 'message': 'Thinking...'})}\n\n"
                await asyncio.sleep(0.2)
                
                result = conversational_handler.handle_general_query(request.message, "en", request.history)
                response_text = result.get("explanation", result.get("response", ""))
                data_list = result.get("data", [])
                
                yield f"data: {json.dumps({'type': 'progress', 'step': 2, 'total': 4, 'status': 'completed', 'message': 'Response ready'})}\n\n"
                await asyncio.sleep(0.05)
            else:
                # Query Odoo or custom tables for data queries
                print(f"[STREAM ENDPOINT] → Using hybrid query system (source: {data_source})")
                yield f"data: {json.dumps({'type': 'progress', 'step': 2, 'total': 4, 'status': 'active', 'message': 'Searching data sources'})}\n\n"
                await asyncio.sleep(0.2)
                
                print(f"[STREAM ENDPOINT] 🔄 Calling route_and_execute_query...")
                result = query_router.route_and_execute_query(request.message, language="en")
                print(f"[STREAM ENDPOINT] ✅ Got result from query_router")
                print(f"[STREAM ENDPOINT] 📦 Result keys: {list(result.keys())}")
                print(f"[STREAM ENDPOINT] 📊 Result data count: {len(result.get('data', []))}")
                print(f"[STREAM ENDPOINT] 💬 Explanation length: {len(result.get('explanation', ''))}")
                
                data_list = result.get("data", [])
                response_text = result.get("explanation", "")
                
                print(f"[STREAM ENDPOINT] ✅ Extracted data_list: {len(data_list)} records")
                print(f"[STREAM ENDPOINT] ✅ Extracted response_text: {len(response_text)} chars")
                if data_list:
                    print(f"[STREAM ENDPOINT] 📋 First data record: {data_list[0]}")
                
                yield f"data: {json.dumps({'type': 'progress', 'step': 2, 'total': 4, 'status': 'completed', 'message': 'Data retrieved'})}\n\n"
                await asyncio.sleep(0.05)
            
            # Step 3: Finalizing response
            yield f"data: {json.dumps({'type': 'progress', 'step': 3, 'total': 4, 'status': 'active', 'message': 'Finalizing response..'})}\n\n"
            await asyncio.sleep(0.2)
            
            # response_text is already set above
            
            # Step 3 Complete
            yield f"data: {json.dumps({'type': 'progress', 'step': 3, 'total': 4, 'status': 'completed', 'message': 'Response ready'})}\n\n"
            await asyncio.sleep(0.05)
            
            # Step 4: Finalizing answer (75-100%)
            yield f"data: {json.dumps({'type': 'progress', 'step': 4, 'total': 4, 'status': 'active', 'message': 'Finalizing answer..'})}\n\n"
            await asyncio.sleep(0.1)
            
            print(f"\n[DATA FLOW CHECK]")
            print(f"  Response text length: {len(response_text)}")
            print(f"  Data list length: {len(data_list)}")
            print(f"  Data list sample: {data_list[:2] if data_list else 'None'}")
            print(f"  Will send chartData: {len(data_list[:15]) if data_list else 0} records\n")
            
            # ============================================
            # STEP 3: Translate response back to user language
            # ============================================
            if translation_service.is_translation_needed(user_language):
                print(f"\n[STREAM] About to translate streaming response to {user_language}")
                print(f"[STREAM] English response length: {len(response_text)} chars")
                print(f"[STREAM] First 800 chars of English response:")
                print(response_text[:800])
                
                response_text = translation_service.translate_from_english(
                    response_text,
                    user_language
                )
                
                print(f"\n[STREAM] Translation complete")
                print(f"[STREAM] Translated response length: {len(response_text)} chars")
                print(f"[STREAM] First 800 chars of translated response:")
                print(response_text[:800])
            
            # Stream the response word by word - FASTER
            words = response_text.split(' ')
            for i, word in enumerate(words):
                chunk_data = {
                    "type": "content",
                    "content": word + (' ' if i < len(words) - 1 else ''),
                    "done": False
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                await asyncio.sleep(0.015)  # 15ms delay (was 30ms) for faster typing
            
            # Send final metadata with chart data
            # Convert to JSON-serializable format (handles Decimal, datetime, etc.)
            chart_data_serializable = jsonable_encoder(data_list[:15]) if len(data_list) > 0 else None
            
            final_data = {
                "type": "complete",
                "content": response_text,
                "done": True,
                "chartData": chart_data_serializable
            }
            print(f"\n[STREAM COMPLETE] Sending final data:")
            print(f"  type: complete")
            print(f"  content length: {len(response_text)}")
            print(f"  done: True")
            print(f"  chartData: {len(final_data['chartData']) if final_data['chartData'] else 0} records")
            print(f"  chartData sample: {final_data['chartData'][:1] if final_data['chartData'] else None}\n")
            yield f"data: {json.dumps(final_data)}\n\n"
            
        except Exception as e:
            error_data = {
                "type": "error",
                "content": str(e),
                "done": True
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/query")
async def direct_query(request: QueryRequest, current_user: dict = Depends(require_auth())):
    try:
        if not conversational_handler.validate_sql(request.sql):
            raise HTTPException(status_code=400, detail="Invalid or unsafe SQL query. Only SELECT queries are allowed.")
        
        data = execute_custom_select_query(request.sql)
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class DetailRequest(BaseModel):
    question: str
    sql: str
    language: str = "en"

@router.post("/chat/details")
async def get_details(request: DetailRequest, current_user: dict = Depends(require_auth())):
    """Get detailed table view for a query - only called when user clicks 'Show Details'"""
    try:
        if not conversational_handler.validate_sql(request.sql):
            raise HTTPException(status_code=400, detail="Invalid SQL query")
        
        # Execute query and get all results
        data_list = execute_custom_select_query(request.sql)
        
        # Generate detailed response with properly formatted tables
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""Generate a properly formatted table view for the data.

STRICT FORMATTING RULES:
1. Start with a brief one-line summary (COUNT MUST BE ACCURATE)
2. Create a well-formatted markdown table:
   - Show ALL data rows (no limit)
   - Use proper column alignment with spaces
   - Align numbers to the right
   - Align text to the left
   - Ensure all columns are properly padded
   - Use consistent spacing between | separators
3. Format currency with $ and thousand separators (1,000.00)
4. COUNT ACCURATELY - verify the number of rows matches actual data
5. NO "remaining records" text - show ALL rows in table

Example format:
| Project Name          | Budget      | Status     |
|:---------------------|------------:|:-----------|
| Infrastructure       | $1,250,000  | Active     |
| Software Dev         | $850,000    | Completed  |

CRITICAL: The table row count MUST match the exact data provided. Do not approximate.

Respond in {request.language}."""},
                {"role": "user", "content": f"Question: {request.question}\n\nData ({len(data_list)} records):\n{str(data_list)}\n\nCreate a well-formatted table showing ALL {len(data_list)} records."}
            ],
            temperature=0.1,
            max_tokens=3000
        )
        
        return {
            "response": response.choices[0].message.content,
            "total_records": len(data_list),
            "data": data_list
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
