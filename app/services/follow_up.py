# import os
# import logging
# import requests
# from datetime import datetime, timezone
# from dotenv import load_dotenv
# from groq import Groq

# # Load environment variables
# load_dotenv()
# GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# BASE_API_URL = os.getenv("BASE_API_URL")  # Default to local server if not set
# # Initialize Groq client
# client = Groq(api_key=GROQ_API_KEY)

# # Configure logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
#   # Replace with your actual API URL

# class QuestionAnalyzer:
#     def __init__(self):
#         self.client = client
    
#     def get_message_history(self, uid):
#         """Retrieve the last 10 messages from the database for a specific user"""
#         try:
#             if not uid:
#                 logger.error("UID is required to fetch message history.")
#                 return []
#             response = requests.get(f"{BASE_API_URL}/api/v1/messages/", params={"uid": uid})
#             response.raise_for_status()
#             all_messages = response.json()
#             message_count = len(all_messages)
#             if message_count == 0:
#                 logger.info(f"No messages found for uid={uid}")
#                 return []
#             if message_count <= 10:
#                 logger.info(f"Found {message_count} messages for uid={uid} (less than or equal to 10)")
#                 return all_messages
#             else:
#                 logger.info(f"Found {message_count} messages for uid={uid} — returning last 10")
#                 return all_messages[-10:]
#         except Exception as e:
#             logger.error(f"Error fetching message history for uid={uid}: {e}")
#             return []
    
#     def analyze_question_context(self, current_question, uid):
#         """
#         Analyze if the current question needs context from previous messages
#         Returns: dict with 'needs_context', 'analysis', and 'enhanced_question'
#         """
#         # First, check if question needs context
#         context_check_prompt = f"""
#         Analyze this question and determine if it needs context from previous conversations:
        
#         Question: "{current_question}"
        
#         Look for:
#         1. References to previous topics (repo names, file names, projects)
#         2. Incomplete commands (missing file names, repo names, etc.)
#         3. Pronouns referring to previous context (it, this, that)
#         4. Commands that seem to continue previous work
#         5. Vague references that need clarification
    
#         Eaxmple:
#         - give me complete A B C and send me back  
#         response with "NO" if it's complete on its own.
#         Respond with only "YES" if it needs previous context, or "NO" if it's complete on its own.
#         """
        
#         try:
#             response = self.client.chat.completions.create(
#                 model="llama-3.3-70b-versatile",
#                 messages=[{"role": "user", "content": context_check_prompt}],
#                 temperature=0.1,
#                 max_completion_tokens=10
#             )
#             needs_context = response.choices[0].message.content.strip().upper() == "YES"
            
#         except Exception as e:
#             logger.error(f"Error analyzing question context: {e}")
#             needs_context = False
        
#         if not needs_context:
#             return {
#                 'needs_context': False,
#                 'analysis': 'Question is complete and self-contained',
#                 'enhanced_question': current_question
#             }
        
#         # If context is needed, get message history and enhance the question
#         return self.enhance_question_with_context(current_question, uid)
    
#     def enhance_question_with_context(self, current_question, uid):
#         """
#         Enhance the current question with context from previous messages
#         """
#         message_history = self.get_message_history(uid)
        
#         if not message_history:
#             return {
#                 'needs_context': True,
#                 'analysis': 'Context needed but no history available',
#                 'enhanced_question': current_question
#             }
        
#         # Format history for context
#         history_text = "\n".join([
#             f"Previous message {i+1}: {msg.get('content', msg.get('text', str(msg)))}"
#             for i, msg in enumerate(message_history)
#         ])
        
#         enhancement_prompt = f"""
#         Based on the conversation history, enhance this current question with missing context:
        
#         CONVERSATION HISTORY:
#         {history_text}
        
#         CURRENT QUESTION: "{current_question}"
        
#         Instructions:
#         1. Identify what context is missing from the current question
#         2. Fill in missing information from the conversation history (repo names, file names, project details, etc.)
#         3. Return a complete, enhanced version of the question that includes all necessary context
#         4. If pushing code, include the repo name and suggest a filename if not mentioned
#         5. Make the question self-contained and clear
        
#         Example:
#         - If history mentions "create repo augai" and current question is "write html signup page and push"
#         - Enhanced: "write html code for signup page, save as signup.html and push to augai repository"
        
#         Return only the enhanced question, nothing else.
#         """
        
#         try:
#             response = self.client.chat.completions.create(
#                 model="llama-3.3-70b-versatile",
#                 messages=[{"role": "user", "content": enhancement_prompt}],
#                 temperature=0.3,
#                 max_completion_tokens=300
#             )
            
#             enhanced_question = response.choices[0].message.content.strip()
            
#             return {
#                 'needs_context': True,
#                 'analysis': 'Question enhanced with context from previous messages',
#                 'enhanced_question': enhanced_question,
#                 'original_question': current_question
#             }
            
#         except Exception as e:
#             logger.error(f"Error enhancing question: {e}")
#             return {
#                 'needs_context': True,
#                 'analysis': f'Error enhancing question: {e}',
#                 'enhanced_question': current_question
#             }
    
#     def process_question(self, question, uid):
#         """
#         Main function to process a question and return the enhanced question
#         """
#         logger.info(f"Processing question for uid={uid}: {question}")
        
#         result = self.analyze_question_context(question, uid)
        
#         logger.info(f"Analysis result: {result['analysis']}")
        
#         if result['needs_context']:
#             logger.info(f"Original: {question}")
#             logger.info(f"Enhanced: {result['enhanced_question']}")
        
#         return result['enhanced_question']

# # Standalone function for easy import and use
# def analyze_and_enhance_question(question, uid, base_api_url=None):
#     """
#     Standalone function to analyze and enhance a question with context
    
#     Args:
#         question (str): The current question to analyze
#         uid (str): User ID for fetching message history
#         base_api_url (str, optional): Override the base API URL
    
#     Returns:
#         str: Enhanced question ready to use
#     """
#     global BASE_API_URL
#     if base_api_url:
#         BASE_API_URL = base_api_url
    
#     analyzer = QuestionAnalyzer()
#     return analyzer.process_question(question, uid)

# # # Usage example
# # def main():
# #     analyzer = QuestionAnalyzer()
    
# #     # Test with a sample UID
# #     test_uid = "user123"
    
# #     # Test questions
# #     test_questions = [
# #         "What is Python?",  # Complete question
# #         "write html code for signup page and push",  # Needs context
# #         "add the login functionality to it",  # Needs context
# #         "create a new repository called myproject"  # Complete question
# #     ]
    
# #     for question in test_questions:
# #         print(f"\n{'='*50}")
# #         print(f"Processing: {question}")
# #         enhanced_question = analyzer.process_question(question, test_uid)
# #         print(f"Enhanced question: {enhanced_question}")

# # # Example of how to use from another file:
# # """
# # # In another file (e.g., your main application):

# # from question_analyzer import analyze_and_enhance_question

# # # Usage
# # uid = "user123"
# # question = "write html signup page and push"
# # enhanced_question = analyze_and_enhance_question(question, uid)

# # print(f"Enhanced question: {enhanced_question}")
# # """

# # if __name__ == "__main__":
# #     main()


import os
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()
openai_api_key = os.getenv("TASK_ANALYZER_OPENAI_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL")  # Default to local server if not set
# Initialize OpenAI client
client = OpenAI(api_key=openai_api_key)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
  # Replace with your actual API URL

class QuestionAnalyzer:
    def __init__(self):
        self.client = client
    
    def get_message_history(self, uid):
        """Retrieve the last 10 messages from the database for a specific user"""
        try:
            if not uid:
                logger.error("UID is required to fetch message history.")
                return []
            response = requests.get(f"{BASE_API_URL}/api/v1/messages/", params={"uid": uid})
            response.raise_for_status()
            all_messages = response.json()
            message_count = len(all_messages)
            if message_count == 0:
                logger.info(f"No messages found for uid={uid}")
                return []
            if message_count <= 10:
                logger.info(f"Found {message_count} messages for uid={uid} (less than or equal to 10)")
                return all_messages
            else:
                logger.info(f"Found {message_count} messages for uid={uid} — returning last 10")
                return all_messages[-10:]
        except Exception as e:
            logger.error(f"Error fetching message history for uid={uid}: {e}")
            return []
    
    def analyze_question_context(self, current_question, uid):
        """
        Analyze if the current question needs context from previous messages
        Returns: dict with 'needs_context', 'analysis', and 'enhanced_question'
        """
        # Enhanced context check prompt with strict criteria and examples
        context_check_prompt = f"""
        Analyze this question and determine if it ACTUALLY needs context from previous conversations to be understood and executed.

        Question: "{current_question}"

        A question NEEDS CONTEXT only if it contains:
        1. Unclear pronouns referring to previous items (it, this, that, them)
        2. Push/deployment commands without specifying repository name
        3. Missing essential information like specific file names, repo names that were mentioned before
        4. Continuation words implying previous work (continue, add to it, update it)
        5. Vague references like "the file", "the repo", "the project" without naming them

        A question does NOT need context if:
        1. It's a greeting, introduction, or politeness (Hi, Hello, Thank you, Please help)
        2. It contains all necessary information within itself
        3. It explicitly names files, repositories, or projects
        4. It's a standalone request or question
        5. It's a general help request

        STRICT EXAMPLES:

        NEEDS CONTEXT (YES):
        - "push the code" (missing repo name)
        - "push it" (missing repo name)
        - "create website and push it" (missing repo name for push)
        - "write html page and push" (missing repo name for push)
        - "add login to it" (what is "it"?)
        - "update the file" (which file?)
        - "continue working on that" (continue what?)
        - "fix the bug there" (where is "there"?)
        - "Add an issue: ‘Add responsive footer’ with high priority." missing project name
        - "set the priority of 1st issue of jira project as low" missing project name

        DOES NOT NEED CONTEXT (NO):

        - "Hi agent Tom, help me push code to repository named 'us'"
        - "create a github repo named myproject" 
        - "write a README.md file"
        - "Hello, can you help with Python?"
        - "Thank you for the help"
        - "Please create a login page with HTML"
        - "write html signup page and push to us repo"
        - "create a mobile shop website"
        - "Create a Jira project called Landing Site."

        Be VERY strict - only return YES if the question is genuinely incomplete without previous context.

        Respond with only "YES" if it needs previous context, or "NO" if it's complete on its own.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": context_check_prompt}],
                temperature=0.1,  # Very low for consistent classification
                max_completion_tokens=10
            )
            needs_context = response.choices[0].message.content.strip().upper() == "YES"
            
        except Exception as e:
            logger.error(f"Error analyzing question context: {e}")
            needs_context = False
        
        if not needs_context:
            return {
                'needs_context': False,
                'analysis': 'Question is complete and self-contained',
                'enhanced_question': current_question
            }
        
        # If context is needed, get message history and enhance the question
        return self.enhance_question_with_context(current_question, uid)

    def enhance_question_with_context(self, current_question, uid):
        """
        Enhance the current question with context from previous messages
        """
        message_history = self.get_message_history(uid)
        
        if not message_history:
            return {
                'needs_context': True,
                'analysis': 'Context needed but no history available',
                'enhanced_question': current_question
            }
        
        # Format history for context - only include user questions, skip replies
        history_text = ""
        count = 0
        for msg in message_history:
            content = msg.get('content', msg.get('text', ''))
            reply = msg.get('reply', '')
            
            if content and content.strip():
                count += 1
                history_text += f"User request {count}: {content.strip()}\n"
                
                # Add bot reply if available
                if reply and reply.strip():
                    history_text += f"Bot reply {count}: {reply.strip()}\n"
                
                history_text += "\n"  # Add spacing between conversations
                
                if count >= 10:  # Limit to last 10 user requests
                    break
        
        if not history_text.strip():
            return {
                'needs_context': True,
                'analysis': 'Context needed but no valid history content available',
                'enhanced_question': current_question
            }
        
        enhancement_prompt = f"""
        Fill in missing information from recent conversation history:

        RECENT CONVERSATION HISTORY:
        {history_text}

        CURRENT INCOMPLETE QUESTION: "{current_question}"

        TASK: Add only the missing essential information (repo name, file name, project name) from the conversation history. Pay special attention to "push" commands that need repository names.
        Instructions:
        1. Identify what context is missing from the current question
        2. Fill in missing information from the conversation history (repo names, file names, project details, etc.)
        3. Return a complete, enhanced version of the question that includes all necessary context
        4. If pushing code, include the repo name and suggest a filename if not mentioned
        5. Make the question self-contained and clear
        
        Example:
        - If history mentions "create repo augai" and current question is "write html signup page and push"
        - Enhanced: "write html code for signup page, save as signup.html and push to augai repository"
        
        EXAMPLES:
        History: "User: create repo myapp" → "Bot: Repository created"
        Current: "push code"
        Enhanced: "push code to myapp repo"

        History: "User: proceed with creating GitHub repository named us" → "Bot: Repository created"
        Current: "now create a 1 mobile shop website page frontend in html and CSS for selling mobile and push it"
        Output like : now create a 1 mobile shop website page frontend in html and CSS for selling mobile in sellingmobile.html and push it to us repository"
        Important:
        history: "User: create a Jira project called Landing Site" → "Bot: Project created"
        current: "Add an issue: Add responsive footer with high priority."
        output like: "Add an issue: Add responsive footer with high priority in the jira project named Landing Site."

        IMPORTANT: If the question mentions "push" or "push it" without specifying a repository, always add the repository name from history.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": enhancement_prompt}],
                temperature=0.1,  # Very low for precise enhancement
                max_completion_tokens=100  # Shorter responses
            )
            
            enhanced_question = response.choices[0].message.content.strip()
            
            # Safety check - prevent over-enhancement
            if len(enhanced_question) > len(current_question) * 2.5:
                logger.warning("Enhancement too verbose, using original question")
                enhanced_question = current_question
            
            return {
                'needs_context': True,
                'analysis': 'Question enhanced with context from previous messages',
                'enhanced_question': enhanced_question,
                'original_question': current_question
            }
            
        except Exception as e:
            logger.error(f"Error enhancing question: {e}")
            return {
                'needs_context': True,
                'analysis': f'Error enhancing question: {e}',
                'enhanced_question': current_question
            }
    def process_question(self, question, uid):
        """
        Main function to process a question and return the enhanced question
        """
        logger.info(f"Processing question for uid={uid}: {question}")
        
        result = self.analyze_question_context(question, uid)
        
        logger.info(f"Analysis result: {result['analysis']}")
        
        if result['needs_context']:
            logger.info(f"Original: {question}")
            logger.info(f"Enhanced: {result['enhanced_question']}")
        
        return result['enhanced_question']

# Standalone function for easy import and use
def analyze_and_enhance_question(question, uid, base_api_url=None):
    """
    Standalone function to analyze and enhance a question with context
    
    Args:
        question (str): The current question to analyze
        uid (str): User ID for fetching message history
        base_api_url (str, optional): Override the base API URL
    
    Returns:
        str: Enhanced question ready to use
    """
    global BASE_API_URL
    if base_api_url:
        BASE_API_URL = base_api_url
    
    analyzer = QuestionAnalyzer()
    return analyzer.process_question(question, uid)

# # Usage example
# def main():
#     analyzer = QuestionAnalyzer()
    
#     # Test with a sample UID
#     test_uid = "user123"
    
#     # Test questions
#     test_questions = [
#         "What is Python?",  # Complete question
#         "write html code for signup page and push",  # Needs context
#         "add the login functionality to it",  # Needs context
#         "create a new repository called myproject"  # Complete question
#     ]
    
#     for question in test_questions:
#         print(f"\n{'='*50}")
#         print(f"Processing: {question}")
#         enhanced_question = analyzer.process_question(question, test_uid)
#         print(f"Enhanced question: {enhanced_question}")

# # Example of how to use from another file:
# """
# # In another file (e.g., your main application):

# from question_analyzer import analyze_and_enhance_question

# # Usage
# uid = "user123"
# question = "write html signup page and push"
# enhanced_question = analyze_and_enhance_question(question, uid)

# print(f"Enhanced question: {enhanced_question}")
# """

# if __name__ == "__main__":
#     main()