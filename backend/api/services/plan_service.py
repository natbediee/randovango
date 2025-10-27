def find_plan_by_id(plan_id):
    # Dummy implementation for example purposes
    return None
def create_new_plan(plan_data):
    # Dummy implementation for example purposes
    return plan_data

def insert_or_update_plan(plan_data):
    # Check if the plan already exists
    existing_plan = find_plan_by_id(plan_data.id)
    if existing_plan:
        # Update the existing plan
        existing_plan.update(plan_data)
        return existing_plan
    else:
        # Insert a new plan
        new_plan = create_new_plan(plan_data)
        return new_plan
