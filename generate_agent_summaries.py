#!/usr/bin/env python3
"""
Generate Agent-Optimized Summaries for Tender Files

This script creates lean, action-oriented summaries designed specifically for
the Bid Management Agent to make intelligent routing decisions. Unlike detailed
summaries that describe file contents, agent summaries focus on:
- What types of questions the file answers
- When to use this file vs. others
- Key metadata for routing decisions

Usage:
    python generate_agent_summaries.py --cluster-id <requirement_cluster_id>
    
The script will:
1. Fetch all files from the specified cluster
2. Generate agent summaries (100-500 words each) using gpt-4o-mini
3. Save summaries to MongoDB as 'agent_summary' field
"""

import os
import sys
import asyncio
import argparse
from typing import List, Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from openai import AsyncOpenAI
from bson import ObjectId

# Load environment variables
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGODB_URL = os.getenv("MONGODB_URL")
MODEL = "gpt-4o"

# Agent Summary Generation Prompt
AGENT_SUMMARY_PROMPT = """You are an expert at creating concise, high-quality summaries of tender document files for AI agent routing decisions.

CRITICAL INSTRUCTIONS:
- Take your time to analyze the document thoroughly
- Think carefully about what information is most useful for routing
- Focus on QUALITY over speed - a well-crafted summary is essential
- Output ONLY the summary text - NO code blocks, NO markdown fences, NO backticks

YOUR TASK:
Transform the document content below into a lean, action-oriented summary (100-400 words) that helps an agent decide WHEN and HOW to use this file.

ANALYSIS FRAMEWORK (think through these before writing):

1. CONTENT ANALYSIS:
   - What is the primary purpose of this document?
   - What types of questions does it answer?
   - What are the key topics/sections?
   - How does it relate to other tender documents?

2. ROUTING METADATA:
   - When should an agent consult this file?
   - What search terms would lead here?
   - Should agent use search_tender_corpus or get_file_content?
   - File size consideration (large files need search, small can be read directly)

3. QUALITY CHECK:
   - Is every sentence necessary?
   - Does it help the agent make routing decisions?
   - Have I avoided including actual answers/details?
   - Is it scannable and action-oriented?

OUTPUT FORMAT (use this structure, but NO markdown code blocks):

**Purpose:** [One clear sentence describing the file's role in the tender]

**Key Topics:**
- [Topic 1: what it covers]
- [Topic 2: what it covers]
- [Topic 3: what it covers]
[Add more if needed, but stay concise]

**Use For:**
- Questions about [specific category or requirement]
- Questions about [specific category or requirement]
- [Additional specific scenarios]

**Metadata:**
- Sections: [number or brief list]
- Related files: [if applicable]
- Recommended tool: [search_tender_corpus / get_file_content / both]
- File size: [small / medium / large]

---

FILE INFORMATION:
- Filename: {filename}
- Estimated pages: {page_count}

DOCUMENT CONTENT (first 15,000 chars):
{detailed_summary}

---

Now, take a moment to think through the analysis framework above, then write a high-quality agent summary (100-400 words). 

REMEMBER: Output ONLY the summary text - do NOT wrap it in code blocks or backticks. Start directly with "**Purpose:**"

Your summary:"""


class AgentSummaryGenerator:
    """Generates lean agent summaries for tender files."""
    
    def __init__(self, mongodb_url: str, openai_api_key: str):
        """Initialize with database and API connections."""
        self.mongo_client = MongoClient(mongodb_url)
        self.db = self.mongo_client["org_1"]
        self.tenders_collection = self.db["tenders"]
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)
        
    def get_files_for_cluster(self, cluster_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all files for a given cluster from proposal_files collection.
        
        Args:
            cluster_id: The cluster ID (MongoDB ObjectId as string)
            
        Returns:
            List of file documents with their extracted markdown
        """
        try:
            # Access proposal_files collection
            proposal_files_collection = self.db["proposal_files"]
            
            # Find all files with this cluster_id (try both string and ObjectId)
            files = list(proposal_files_collection.find({
                "cluster_id": cluster_id
            }))
            
            # If not found as string, try as ObjectId
            if not files:
                files = list(proposal_files_collection.find({
                    "cluster_id": ObjectId(cluster_id)
                }))
            
            if not files:
                print(f"❌ No files found for cluster ID: {cluster_id}")
                return []
            
            print(f"✓ Found {len(files)} files in proposal_files collection")
            
            # Show cluster info from first file
            if files:
                first_file = files[0]
                print(f"✓ Cluster: {first_file.get('file_name', 'Unknown')}")
            
            return files
            
        except Exception as e:
            print(f"❌ Error fetching files: {e}")
            return []
    
    async def generate_agent_summary(
        self, 
        filename: str, 
        detailed_summary: str,
        page_count: Optional[int] = None
    ) -> Optional[str]:
        """
        Generate a lean agent summary from a detailed summary.
        
        Args:
            filename: Name of the file
            detailed_summary: The existing detailed summary
            page_count: Number of pages (if available)
            
        Returns:
            Agent-optimized summary or None if generation fails
        """
        try:
            # Handle missing or empty summaries
            if not detailed_summary or detailed_summary.strip() == "":
                detailed_summary = f"[No detailed summary available for {filename}]"
            
            # Build prompt
            prompt = AGENT_SUMMARY_PROMPT.format(
                filename=filename,
                page_count=page_count or "Unknown",
                detailed_summary=detailed_summary[:15000]  # Truncate if too long
            )
            
            # Call llm
            response = await self.openai_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at creating concise, action-oriented summaries for AI agent decision-making."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Low temperature for consistency
                max_tokens=800,   # ~500 words max
            )
            
            agent_summary = response.choices[0].message.content.strip()
            
            # Clean up any markdown code blocks that slipped through
            # Remove opening code blocks
            if agent_summary.startswith("```markdown"):
                agent_summary = agent_summary[len("```markdown"):].strip()
            elif agent_summary.startswith("```"):
                agent_summary = agent_summary[3:].strip()
            
            # Remove closing code blocks
            if agent_summary.endswith("```"):
                agent_summary = agent_summary[:-3].strip()
            
            # Remove any inline code blocks around the whole thing
            agent_summary = agent_summary.strip('`').strip()
            
            # Validate length (rough word count)
            word_count = len(agent_summary.split())
            if word_count > 500:
                print(f"  ⚠️  Summary too long ({word_count} words), truncating...")
                words = agent_summary.split()[:450]
                agent_summary = " ".join(words) + "..."
            
            return agent_summary
            
        except Exception as e:
            print(f"  ❌ Error generating summary: {e}")
            return None
    
    async def process_file(
        self, 
        file_doc: Dict[str, Any], 
        index: int, 
        total: int
    ) -> Dict[str, Any]:
        """
        Process a single file: generate agent summary from extracted markdown.
        
        Args:
            file_doc: File document from MongoDB (proposal_files collection)
            index: Current file index (for progress tracking)
            total: Total number of files
            
        Returns:
            Updated file document with agent_summary field
        """
        filename = file_doc.get("file_name", "Unknown")
        file_id = file_doc.get("_id", "Unknown")
        
        print(f"\n[{index}/{total}] Processing: {filename}")
        
        # Get extracted markdown (this is the source content)
        extracted_markdown = file_doc.get("extracted_markdown", "")
        
        if not extracted_markdown or extracted_markdown.strip() == "":
            print(f"  ⚠️  No extracted markdown found, skipping")
            return file_doc
        
        # Calculate token/page estimate
        token_count = file_doc.get("tokens", 0)
        page_estimate = token_count // 500 if token_count else None
        
        print(f"  📄 Markdown length: {len(extracted_markdown)} chars")
        if token_count:
            print(f"  📊 Tokens: {token_count} (~{page_estimate} pages)")
        
        # Generate agent summary from extracted markdown
        print(f"  🤖 Calling gpt-4o...")
        agent_summary = await self.generate_agent_summary(
            filename=filename,
            detailed_summary=extracted_markdown[:15000],  # Use markdown as "summary"
            page_count=page_estimate
        )
        
        if agent_summary:
            word_count = len(agent_summary.split())
            print(f"  ✓ Generated agent summary ({word_count} words)")
            file_doc["agent_summary"] = agent_summary
            file_doc["agent_summary_generated_at"] = datetime.utcnow()
            return file_doc
        else:
            print(f"  ❌ Failed to generate agent summary")
            return file_doc
    
    async def process_all_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process all files in parallel (with controlled concurrency).
        
        Args:
            files: List of file documents
            
        Returns:
            List of updated file documents
        """
        total = len(files)
        print(f"\n{'='*70}")
        print(f"📝 Generating Agent Summaries for {total} Files")
        print(f"{'='*70}")
        
        # Process files with controlled concurrency (5 at a time)
        semaphore = asyncio.Semaphore(5)
        
        async def process_with_semaphore(file_doc, index):
            async with semaphore:
                return await self.process_file(file_doc, index + 1, total)
        
        tasks = [
            process_with_semaphore(file_doc, i) 
            for i, file_doc in enumerate(files)
        ]
        
        updated_files = await asyncio.gather(*tasks)
        
        # Count successful generations
        success_count = sum(1 for f in updated_files if "agent_summary" in f)
        
        print(f"\n{'='*70}")
        print(f"✓ Completed: {success_count}/{total} agent summaries generated")
        print(f"{'='*70}")
        
        return updated_files
    
    def save_summaries_to_mongodb(
        self, 
        cluster_id: str, 
        updated_files: List[Dict[str, Any]]
    ) -> bool:
        """
        Save agent summaries back to MongoDB proposal_files collection.
        
        Args:
            cluster_id: Cluster ID
            updated_files: List of files with agent_summary field
            
        Returns:
            True if successful, False otherwise
        """
        try:
            print(f"\n💾 Saving agent summaries to MongoDB...")
            
            proposal_files_collection = self.db["proposal_files"]
            
            # Update each file individually
            success_count = 0
            for file_doc in updated_files:
                if "agent_summary" in file_doc:
                    result = proposal_files_collection.update_one(
                        {"_id": file_doc["_id"]},
                        {
                            "$set": {
                                "agent_summary": file_doc["agent_summary"],
                                "agent_summary_generated_at": file_doc["agent_summary_generated_at"]
                            }
                        }
                    )
                    if result.modified_count > 0:
                        success_count += 1
            
            if success_count > 0:
                print(f"✓ Successfully saved {success_count} agent summaries to proposal_files")
                return True
            else:
                print(f"⚠️  No files were updated in MongoDB")
                return False
                
        except Exception as e:
            print(f"❌ Error saving to MongoDB: {e}")
            return False
    
    async def generate_summaries_for_cluster(self, cluster_id: str) -> bool:
        """
        Main workflow: Generate and save agent summaries for a cluster.
        
        Args:
            cluster_id: Requirement cluster ID
            
        Returns:
            True if successful, False otherwise
        """
        print(f"\n{'='*70}")
        print(f"🚀 AGENT SUMMARY GENERATOR")
        print(f"{'='*70}")
        print(f"Cluster ID: {cluster_id}")
        print(f"Model: {MODEL}")
        print(f"Target: 100-500 words per file")
        print(f"{'='*70}\n")
        
        # Step 1: Fetch files
        files = self.get_files_for_cluster(cluster_id)
        if not files:
            return False
        
        # Step 2: Generate agent summaries
        updated_files = await self.process_all_files(files)
        
        # Step 3: Save to MongoDB
        success = self.save_summaries_to_mongodb(cluster_id, updated_files)
        
        if success:
            print(f"\n✅ COMPLETE! Agent summaries generated and saved.")
            print(f"\n💡 Next steps:")
            print(f"   1. Update ReactAgent to use 'agent_summary' instead of 'summary'")
            print(f"   2. Test latency and tool usage with new summaries")
            print(f"   3. Monitor agent behavior for accuracy\n")
        
        return success
    
    def close(self):
        """Close database connection."""
        self.mongo_client.close()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate agent-optimized summaries for tender files"
    )
    parser.add_argument(
        "--cluster-id",
        required=True,
        help="Requirement cluster ID (MongoDB ObjectId)"
    )
    
    args = parser.parse_args()
    
    # Validate environment variables
    if not MONGODB_URL:
        print("❌ Error: MONGODB_URL not found in environment")
        sys.exit(1)
    
    if not OPENAI_API_KEY:
        print("❌ Error: OPENAI_API_KEY not found in environment")
        sys.exit(1)
    
    # Initialize generator
    generator = AgentSummaryGenerator(
        mongodb_url=MONGODB_URL,
        openai_api_key=OPENAI_API_KEY
    )
    
    try:
        # Generate summaries
        success = await generator.generate_summaries_for_cluster(args.cluster_id)
        sys.exit(0 if success else 1)
    finally:
        generator.close()


if __name__ == "__main__":
    asyncio.run(main())

