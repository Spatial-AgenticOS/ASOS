"""
THEORA Skill Implementations
============================
Concrete Python backing implementations for JSON skill schemas.
"""
from typing import Dict, Type
from skills.base import BaseSkill

# Registry mapping skill_id -> Python Class implementation
SKILL_IMPLEMENTATIONS: Dict[str, Type[BaseSkill]] = {}

def register_skill(skill_class: Type[BaseSkill]):
    """Decorator to register a python skill implementation."""
    def wrapper():
        # Instantiate it to get the ID, or read standard class property
        instance = skill_class()
        SKILL_IMPLEMENTATIONS[instance.skill_id] = instance
        return skill_class
    
    wrapper()
    return skill_class

def get_implementation(skill_id: str) -> BaseSkill | None:
    """Retrieve the instantiated python logic instance for a skill."""
    return SKILL_IMPLEMENTATIONS.get(skill_id)

# Auto-load standard implementations below
try:
    import skills.impl.web_search
except ImportError:
    pass
