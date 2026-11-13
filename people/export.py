from core.export import stamp, workbook_response


def people_workbook(people):
    rows = [
        (
            p.pk,
            p.name,
            p.phone,
            p.email,
            p.get_gender_display(),
            p.address,
            p.current_employer,
            p.current_salary,
            p.expected_salary,
            p.experience_years,
            p.joining_period,
            p.get_contact_status_display(),
            p.get_priority_display(),
            p.company.name,
            p.candidate_id,
        )
        for p in people.select_related("company")
    ]
    return workbook_response(
        stamp("people"),
        {
            "People": (
                (
                    "Card #",
                    "Name",
                    "Phone",
                    "Email",
                    "Gender",
                    "Address",
                    "Current employer",
                    "Current salary",
                    "Expected salary",
                    "Experience (years)",
                    "Joining period",
                    "Contact status",
                    "Priority",
                    "Company",
                    "Candidate ID",
                ),
                rows,
            )
        },
    )
