#!/usr/bin/env python3
from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()
mongo_client = MongoClient(os.getenv('MONGODB_URL'))
db = mongo_client['org_1']
proposal_files = db['proposal_files']

# Get one file with agent_summary
file_doc = proposal_files.find_one({
    'cluster_id': '68c99b8a10844521ad051543',
    'agent_summary': {'$exists': True}
})

if file_doc:
    print(f'File: {file_doc.get("file_name")}')
    print(f'Word count: {len(file_doc["agent_summary"].split())} words')
    print()
    print('Agent Summary Preview:')
    print('=' * 70)
    print(file_doc['agent_summary'][:700])
    print()
    if len(file_doc['agent_summary']) > 700:
        print('...(truncated for display)...')
        print()
    
    # Check for code blocks
    summary = file_doc['agent_summary']
    has_code_blocks = '```' in summary
    print('=' * 70)
    print(f'Has code blocks: {has_code_blocks}')
    print(f'Starts correctly: {summary.strip().startswith("**Purpose:**")}')
    print(f'Total length: {len(summary)} chars')
else:
    print('No file with agent_summary found')

