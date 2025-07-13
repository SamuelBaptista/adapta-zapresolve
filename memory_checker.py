#!/usr/bin/env python3
"""
Memory Checker Script
Diagnoses Redis memory corruption and malformed chat history data
"""

import redis
import json
import sys
from typing import Dict, Any, List

class MemoryChecker:
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        try:
            self.redis_client = redis.Redis(
                host=redis_host, 
                port=redis_port, 
                decode_responses=True
            )
            self.redis_client.ping()
            print(f"✅ Connected to Redis at {redis_host}:{redis_port}")
        except Exception as e:
            print(f"❌ Failed to connect to Redis: {e}")
            sys.exit(1)
    
    def get_all_memory_keys(self) -> List[str]:
        """Get all memory-related keys from Redis"""
        try:
            keys = self.redis_client.keys("*")
            # Handle potential None return
            if not keys:
                return []
            # Convert and filter keys
            return [str(key) for key in keys if str(key).startswith("wpp_memory_") or "memory" in str(key).lower()]
        except Exception as e:
            print(f"❌ Error getting Redis keys: {e}")
            return []
    
    def analyze_memory_key(self, key: str) -> Dict[str, Any]:
        """Analyze a specific memory key"""
        try:
            data = self.redis_client.get(key)
            if not data:
                return {"error": "Key not found or empty"}
            
            # Ensure data is string
            data_str = str(data)
            
            # Try to parse as JSON
            try:
                parsed_data = json.loads(data_str)
                return {
                    "key": key,
                    "type": type(parsed_data).__name__,
                    "data": parsed_data,
                    "valid_json": True
                }
            except json.JSONDecodeError as e:
                return {
                    "key": key,
                    "type": "string",
                    "data": data_str,
                    "valid_json": False,
                    "json_error": str(e)
                }
        except Exception as e:
            return {"error": f"Failed to analyze key {key}: {e}"}
    
    def check_chat_history_format(self, chat_history: List[Dict]) -> Dict[str, Any]:
        """Check if chat history is properly formatted"""
        issues = []
        
        if not isinstance(chat_history, list):
            return {"valid": False, "issues": ["Chat history is not a list"]}
        
        for i, message in enumerate(chat_history):
            if not isinstance(message, dict):
                issues.append(f"Message {i} is not a dictionary")
                continue
            
            # Check required fields
            if "role" not in message:
                issues.append(f"Message {i} missing 'role' field")
            elif message["role"] not in ["user", "assistant", "system"]:
                issues.append(f"Message {i} has invalid role: {message['role']}")
            
            if "content" not in message:
                issues.append(f"Message {i} missing 'content' field")
            else:
                content = message["content"]
                # Check content format
                if isinstance(content, dict):
                    issues.append(f"Message {i} content is dict (should be string or array)")
                elif isinstance(content, list):
                    # Check if it's a valid content array
                    for j, item in enumerate(content):
                        if not isinstance(item, dict):
                            issues.append(f"Message {i} content[{j}] is not a dict")
                        elif "type" not in item:
                            issues.append(f"Message {i} content[{j}] missing 'type' field")
                elif not isinstance(content, str):
                    issues.append(f"Message {i} content is {type(content).__name__} (should be string or array)")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "message_count": len(chat_history)
        }
    
    def full_diagnosis(self) -> None:
        """Run a full memory diagnosis"""
        print("\n🔍 REDIS MEMORY DIAGNOSIS")
        print("=" * 50)
        
        # Get all memory keys
        memory_keys = self.get_all_memory_keys()
        print(f"📊 Found {len(memory_keys)} memory-related keys")
        
        if not memory_keys:
            print("✅ No memory keys found - clean slate")
            return
        
        # Analyze each key
        for key in memory_keys:
            print(f"\n📋 Analyzing key: {key}")
            print("-" * 30)
            
            analysis = self.analyze_memory_key(key)
            
            if "error" in analysis:
                print(f"❌ Error: {analysis['error']}")
                continue
            
            print(f"🔧 Type: {analysis['type']}")
            print(f"📝 Valid JSON: {analysis['valid_json']}")
            
            if not analysis['valid_json']:
                print(f"❌ JSON Error: {analysis['json_error']}")
                print(f"📄 Raw data: {analysis['data'][:200]}...")
                continue
            
            data = analysis['data']
            
            # Check if it has chat_history
            if isinstance(data, dict) and 'chat_history' in data:
                chat_history = data['chat_history']
                print(f"💬 Chat History Found: {len(chat_history)} messages")
                
                # Validate chat history format
                validation = self.check_chat_history_format(chat_history)
                
                if validation['valid']:
                    print("✅ Chat history format is valid")
                else:
                    print(f"❌ Chat history format issues ({len(validation['issues'])} problems):")
                    for issue in validation['issues']:
                        print(f"   • {issue}")
                
                # Show sample messages
                print(f"\n📝 Sample messages:")
                for i, message in enumerate(chat_history[:3]):  # Show first 3
                    print(f"   Message {i}: {json.dumps(message, indent=2)}")
                    if i >= 2:
                        break
                
                if len(chat_history) > 3:
                    print(f"   ... and {len(chat_history) - 3} more messages")
            
            else:
                print(f"📄 Data preview: {json.dumps(data, indent=2)[:300]}...")
    
    def clear_corrupted_memory(self, confirm: bool = False) -> None:
        """Clear corrupted memory entries"""
        if not confirm:
            print("⚠️  Use --clear-corrupted to actually clear corrupted entries")
            return
        
        memory_keys = self.get_all_memory_keys()
        cleared_count = 0
        
        for key in memory_keys:
            analysis = self.analyze_memory_key(key)
            
            if "error" in analysis or not analysis.get('valid_json', False):
                print(f"🗑️  Clearing corrupted key: {key}")
                self.redis_client.delete(key)
                cleared_count += 1
                continue
            
            data = analysis['data']
            if isinstance(data, dict) and 'chat_history' in data:
                validation = self.check_chat_history_format(data['chat_history'])
                if not validation['valid']:
                    print(f"🗑️  Clearing malformed chat history: {key}")
                    self.redis_client.delete(key)
                    cleared_count += 1
        
        print(f"✅ Cleared {cleared_count} corrupted memory entries")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Check Redis memory for corruption")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--clear-corrupted", action="store_true", help="Clear corrupted entries")
    
    args = parser.parse_args()
    
    checker = MemoryChecker(args.host, args.port)
    checker.full_diagnosis()
    
    if args.clear_corrupted:
        checker.clear_corrupted_memory(confirm=True)

if __name__ == "__main__":
    main() 