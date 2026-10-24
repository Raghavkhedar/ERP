from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class DailyPlan(models.Model):
    """What someone means to do on one day: their goals and the work behind them."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="daily_plans"
    )
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"], name="plans_one_plan_per_user_day"
            ),
        ]

    def __str__(self):
        return f"{self.user} on {self.date}"


class PlanItem(models.Model):
    class Kind(models.TextChoices):
        GOAL = "goal", "Goal"
        WORK = "work", "Work"

    plan = models.ForeignKey(DailyPlan, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=4, choices=Kind.choices)
    text = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    history = HistoricalRecords()

    class Meta:
        ordering = ["kind", "position", "id"]
        indexes = [
            models.Index(fields=["plan", "kind"], name="plans_item_plan_kind_idx"),
        ]

    def __str__(self):
        return self.text
