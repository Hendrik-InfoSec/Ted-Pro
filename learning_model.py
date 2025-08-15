import json
from collections import defaultdict

class LearningModule:
    def __init__(self, client_id):
        self.client_id = client_id
        self.query_counts = defaultdict(int)
        
    def should_learn(self, query):
        """Learn if query contains money/shipping terms"""
        money_terms = ['price', 'cost', '$', 'ship', 'delivery']
        return any(term in query.lower() for term in money_terms)
    
    def log_query(self, query):
        self.query_counts[query] += 1
        return self.query_counts[query] >= 3  # Learn after 3 repeats