"""
Simple test for ReactAgentMemory with 5-10 questions.
Tracks response times and evaluates memory using ChatOpenAI.
"""

import asyncio
import sys
import os
from datetime import datetime
from typing import List
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from react_agent_memory import ReactAgentMemory


class MemoryEvaluation(BaseModel):
    """Structured evaluation of conversation memory."""
    memory_maintained: bool = Field(description="Whether agent maintained context across all queries")
    reasoning: str = Field(description="Brief explanation of memory performance")
    confidence: float = Field(description="Confidence score 0.0-1.0")


async def test_conversation(questions: List[str], thread_id: str = None):
    """
    Test agent with multiple questions and evaluate memory.
    
    Args:
        questions: List of 5-10 questions to ask
        thread_id: Optional thread ID (auto-generated if not provided)
    """
    if not (5 <= len(questions) <= 10):
        print("❌ Please provide between 5 and 10 questions")
        return
    
    thread_id = thread_id or f"test_{datetime.now().timestamp()}"
    
    print(f"\n{'='*70}")
    print(f"🧪 Testing ReactAgentMemory with {len(questions)} questions")
    print(f"Thread ID: {thread_id}")
    print(f"{'='*70}\n")

    agent = ReactAgentMemory(org_id=1)
 
    results = []
    conversation_log = []

    for i, question in enumerate(questions, 1):
        print(f"\n--- Question {i}/{len(questions)} ---")
        print(f"Q: {question}")
        
        result = await agent.chat_sync(question, thread_id)
        
        response_time = result.get('processing_time_ms', 0)
        response = result.get('response', '')
        success = result.get('success', False)
        
        results.append({
            'question': question,
            'response': response,
            'time_ms': response_time,
            'success': success
        })
        
        conversation_log.append(f"User: {question}")
        conversation_log.append(f"Agent: {response[:200]}...")
        
        status = "✅" if success else "❌"
        print(f"A: {response[:100]}...")
        print(f"{status} Time: {response_time}ms")

    print(f"\n{'='*70}")
    print("⏱️  RESPONSE TIME SUMMARY")
    print(f"{'='*70}\n")
    
    for i, result in enumerate(results, 1):
        status = "✅" if result['success'] else "❌"
        print(f"{i}. {status} {result['time_ms']:>6}ms - {result['question'][:50]}...")
    
    total_time = sum(r['time_ms'] for r in results)
    avg_time = total_time / len(results)
    print(f"\nTotal Time: {total_time}ms")
    print(f"Average Time: {avg_time:.0f}ms")

    print(f"\n{'='*70}")
    print("🧠 MEMORY EVALUATION (ChatOpenAI)")
    print(f"{'='*70}\n")
    
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(MemoryEvaluation)
    
    eval_prompt = f"""Evaluate if the AI agent maintained context and memory across this conversation.

Questions asked ({len(questions)} total):
{chr(10).join(f"{i}. {q}" for i, q in enumerate(questions, 1))}

Conversation Log:
{chr(10).join(conversation_log)}

Determine if the agent:
1. Remembered information from earlier in the conversation
2. Referenced or used context from previous questions
3. Demonstrated continuous conversation awareness

Provide your evaluation."""
    
    evaluation = await llm.ainvoke(eval_prompt)
    
    print(f"Memory Maintained: {'✅ YES' if evaluation.memory_maintained else '❌ NO'}")
    print(f"Confidence: {evaluation.confidence:.0%}")
    print(f"Reasoning: {evaluation.reasoning}")

    agent.cleanup()
    
    print(f"\n{'='*70}")
    print("✨ Test Complete")
    print(f"{'='*70}\n")
    
    return {
        'results': results,
        'evaluation': evaluation,
        'total_time': total_time,
        'avg_time': avg_time
    }

EXAMPLE_QUESTIONS = {
    'tender_analysis': [
        "Hvilke obligatoriske ydelsesområder indgår i Rammeaftale 02.15?",
        "Describe in detail any 3 of them.",
        "What was my first question about?",
        "What tools did you use to answer the first question?",
        "Summarize what we've discussed so far."
    ],
    
    'general': [
        "My name is Alice and I'm working on Project Phoenix.",
        "What's my name?",
        "What project am I working on?",
        "Tell me about cloud security best practices.",
        "How does this relate to my project?",
        "What have we discussed in this conversation?"
    ],
    
    'technical': [
        "I need to analyze a tender for cloud infrastructure.",
        "What are the key requirements I should look for?",
        "What was I analyzing?",
        "List the top 3 requirements you mentioned.",
        "How would you prioritize these requirements?",
        "Can you summarize our entire discussion?"
    ]
}

async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test ReactAgentMemory with multiple questions")
    parser.add_argument(
        '--example',
        choices=list(EXAMPLE_QUESTIONS.keys()),
        help='Use example question set'
    )
    parser.add_argument(
        '--questions',
        nargs='+',
        help='Custom questions (provide 5-10)'
    )
    
    args = parser.parse_args()
    
    if args.questions:
        questions = args.questions
    elif args.example:
        questions = EXAMPLE_QUESTIONS[args.example]
    else:
        questions = EXAMPLE_QUESTIONS['tender_analysis']
    
    result = await test_conversation(questions)
    
    return 0 if result['evaluation'].memory_maintained else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)