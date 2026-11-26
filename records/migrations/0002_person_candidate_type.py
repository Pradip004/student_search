from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("records", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="person",
            name="person_type",
            field=models.CharField(
                choices=[
                    ("student", "Student"),
                    ("candidate", "Candidate"),
                    ("employee", "Employee"),
                ],
                max_length=10,
            ),
        ),
    ]
