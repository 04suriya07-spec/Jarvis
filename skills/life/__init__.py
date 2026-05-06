"""Life integration skills."""
from skills.life.files import FileSkill
from skills.life.calendar_skill import CalendarSkill
from skills.life.tasks import TasksSkill
from skills.life.browser import BrowserSkill

__all__ = ["FileSkill", "CalendarSkill", "TasksSkill", "BrowserSkill"]
