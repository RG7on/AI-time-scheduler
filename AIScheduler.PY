import random
import csv
import os
import math
import json
from ortools.sat.python import cp_model
import os
from dotenv import load_dotenv

load_dotenv()

# Maximum students per section
MAX_SECTION_SIZE = 30

# Directory to save the CSV file
save_directory = os.getenv('CSV_DIRECTORY_PATH')

# Ensure the directory exists
if not os.path.exists(save_directory):
    os.makedirs(save_directory)

# Load data from dataset.json
with open('dataset.json', 'r') as f:
    data = json.load(f)

# Extract data
courses = data['courses']
teachers = data['teachers']
rooms = data['rooms']
time_slots = data['time_slots']
students = data['students']

# Define room capacities (assuming all rooms have capacity 30 for simplicity)
# Update this dictionary based on actual room capacities if needed
room_capacities = {room: 30 for room in rooms}

# Mapping courses to teachers
course_teacher = {}
for teacher, info in teachers.items():
    for course in info['courses']:
        course_teacher[course] = teacher

# Verify that all courses have an assigned teacher
for course in courses:
    if course not in course_teacher:
        raise ValueError(f"Course '{course}' is not assigned to any teacher.")

# Determine the number of sections per course
course_enrollments = {}
total_sections_needed = 0  # Initialize total sections needed
for course in courses:
    enrolled_students = [student for student, enrolled in students.items() if course in enrolled]
    num_students = len(enrolled_students)
    num_sections = math.ceil(num_students / MAX_SECTION_SIZE)
    total_sections_needed += num_sections  # Accumulate total sections needed
    course_enrollments[course] = {
        'students': enrolled_students,
        'num_students': num_students,
        'num_sections': num_sections
    }

# Create sections for each course
sections = []
section_course = {}
section_teacher = {}
section_students = {}

for course, cdata in course_enrollments.items():
    num_sections = cdata['num_sections']
    students_list = cdata['students']
    teacher = course_teacher[course]
    # Split students into sections
    for i in range(num_sections):
        section_id = f"{course}_S{i+1}"
        sections.append(section_id)
        section_course[section_id] = course
        section_teacher[section_id] = teacher
        # Assign students to this section
        start_idx = i * MAX_SECTION_SIZE
        end_idx = start_idx + MAX_SECTION_SIZE
        section_students_list = students_list[start_idx:end_idx]
        section_students[section_id] = section_students_list

# Update students' enrolled sections
student_sections = {student: [] for student in students}
for section_id, students_in_section in section_students.items():
    for student in students_in_section:
        student_sections[student].append(section_id)

# Preliminary Feasibility Check

total_sections = len(sections)
total_time_slots = len(time_slots)
total_rooms = len(rooms)
max_capacity = total_time_slots * total_rooms

if total_sections > max_capacity:
    shortage = total_sections - max_capacity
    print(f"No feasible schedule can be generated: the number of sections needed ({total_sections}) exceeds the total available slots ({max_capacity}) by {shortage} sections.")
    print("Consider increasing the number of rooms, time slots, or maximum section size to accommodate all sections.")
    exit()
else:
    print(f"Total sections needed: {total_sections}")
    print(f"Total available slots: {max_capacity}")

# Teacher Capacity Check

teacher_max_sections = len(time_slots)  # Assuming full availability
infeasible_teachers = []

max_sessions_per_day = 5  # Maximum sessions per day for a teacher

for teacher in teachers:
    teacher_sections = [sec for sec, t in section_teacher.items() if t == teacher]
    num_sections = len(teacher_sections)
    if num_sections > teacher_max_sections:
        infeasible_teachers.append((teacher, num_sections))
    if num_sections > max_sessions_per_day * 5:
        infeasible_teachers.append((teacher, num_sections))

if infeasible_teachers:
    print("No feasible schedule can be generated due to teacher capacity constraints.")
    for teacher, num_sections in infeasible_teachers:
        print(f"{teacher} has {num_sections} sections to teach but exceeds the maximum allowed.")
    exit()

# CSP Model
model = cp_model.CpModel()

# Decision variables: section -> time_slot
section_slot = {}
for section in sections:
    section_slot[section] = model.NewIntVar(1, len(time_slots), f'{section}_slot')

# Decision variables: section -> room
section_room = {}
for section in sections:
    section_room[section] = model.NewIntVar(0, len(rooms) - 1, f'{section}_room')

# Create combined variables for time slot and room
combined_slot_room = {}
for section in sections:
    combined_slot_room[section] = model.NewIntVar(0, len(time_slots) * len(rooms) - 1, f'{section}_combined')
    model.Add(combined_slot_room[section] == (section_slot[section] - 1) * len(rooms) + section_room[section])

# Create a mapping from slots to days
slot_to_day_list = [(slot_num - 1) // 5 for slot_num in range(1, len(time_slots) + 1)]

# Create variables for section days
section_day = {}
for sec in sections:
    section_day[sec] = model.NewIntVar(0, 4, f'section_day_{sec}')
    tmp_index = model.NewIntVar(0, len(time_slots) - 1, f'tmp_index_{sec}')
    model.Add(tmp_index == section_slot[sec] - 1)
    model.AddElement(tmp_index, slot_to_day_list, section_day[sec])

# Function to calculate slot number
def get_slot_number(day_index, slot_in_day):
    return day_index * 5 + slot_in_day

# Hard Constraints

# 1. No teacher conflict
for teacher in teachers:
    teacher_sections = [sec for sec, t in section_teacher.items() if t == teacher]
    for i in range(len(teacher_sections)):
        for j in range(i + 1, len(teacher_sections)):
            s1 = teacher_sections[i]
            s2 = teacher_sections[j]
            model.Add(section_slot[s1] != section_slot[s2])

# 2. No student conflict
for student, enrolled_sections in student_sections.items():
    for i in range(len(enrolled_sections)):
        for j in range(i + 1, len(enrolled_sections)):
            s1 = enrolled_sections[i]
            s2 = enrolled_sections[j]
            model.Add(section_slot[s1] != section_slot[s2])

# 3. No room conflict: combined_slot_room variables must be all different
model.AddAllDifferent([combined_slot_room[section] for section in sections])

# 4. Teacher unavailable slots (if any)
for section in sections:
    teacher = section_teacher[section]
    unavailable_slots = [int(s.replace('Slot', '')) for s in teachers[teacher]['unavailable']]
    for slot in unavailable_slots:
        model.Add(section_slot[section] != slot)

# 5. No courses on restricted time slots
# List of restricted slots (as tuples of day index and slot in day)
restricted_slots = [(2, 2)]  # Tuesday, Slot 2 (10:00-12:00)

# Calculate slot numbers for restricted slots
restricted_slot_numbers = [get_slot_number(day, slot) for day, slot in restricted_slots]

# Apply constraints
for section in sections:
    for restricted_slot in restricted_slot_numbers:
        model.Add(section_slot[section] != restricted_slot)

# 6. Room capacity constraints
for section in sections:
    room_var = section_room[section]
    num_students_in_section = len(section_students[section])
    for room_idx, room_name in enumerate(rooms):
        capacity = room_capacities[room_name]
        if num_students_in_section > capacity:
            # Section cannot be assigned to this room
            model.Add(room_var != room_idx)

# 7. Teacher workload per day constraint
for teacher in teachers:
    teacher_sections = [sec for sec, t in section_teacher.items() if t == teacher]
    for day in range(5):  # Days 0 to 4
        sessions_on_day = []
        for sec in teacher_sections:
            is_on_day = model.NewBoolVar(f'{sec}_is_on_day_{day}')
            # Reified constraints to define is_on_day
            model.Add(section_day[sec] == day).OnlyEnforceIf(is_on_day)
            model.Add(section_day[sec] != day).OnlyEnforceIf(is_on_day.Not())
            sessions_on_day.append(is_on_day)
        if sessions_on_day:
            # Limit the number of sessions per day for the teacher
            model.Add(sum(sessions_on_day) <= max_sessions_per_day)

# Soft Constraints - To be minimized in the objective function

# 8. Spread courses across days (minimize clustering)
course_day_vars = {}
for course in courses:
    sections_of_course = [sec for sec in sections if section_course[sec] == course]
    for day in range(5):  # Days 0 to 4
        day_var = model.NewBoolVar(f'{course}_on_day_{day}')
        course_day_vars[(course, day)] = day_var
        for sec in sections_of_course:
            is_on_day = model.NewBoolVar(f'{sec}_is_on_day_{day}')
            # Reified constraints to define is_on_day
            model.Add(section_day[sec] == day).OnlyEnforceIf(is_on_day)
            model.Add(section_day[sec] != day).OnlyEnforceIf(is_on_day.Not())
            # Link day_var and is_on_day
            model.AddImplication(is_on_day, day_var)
        # No need to add to the objective; we'll handle it below

# 9. Minimize gaps in student schedules
student_first_last_slots = {}
for student in students:
    slots = [section_slot[sec] for sec in student_sections[student]]
    if slots:
        student_first_last_slots[student] = (
            model.NewIntVar(1, len(time_slots), f'{student}_first_slot'),
            model.NewIntVar(1, len(time_slots), f'{student}_last_slot')
        )
        model.AddMinEquality(student_first_last_slots[student][0], slots)
        model.AddMaxEquality(student_first_last_slots[student][1], slots)

# Objective Function
objective_terms = []

# a. Minimize the number of days courses are clustered on
for course in courses:
    days_active = [course_day_vars[(course, day)] for day in range(5)]
    # We want to maximize the number of days a course is taught on
    # Since we can only minimize in CP-SAT, we minimize the negative sum
    objective_terms.append(-sum(days_active))

# b. Minimize gaps in student schedules
for student in student_first_last_slots:
    first_slot, last_slot = student_first_last_slots[student]
    # Minimize the time span of the student's schedule
    objective_terms.append(last_slot - first_slot)

# Define the objective function
model.Minimize(sum(objective_terms))

# Solve CSP
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 300  # Optional: set a time limit

status = solver.Solve(model)

if status == cp_model.INFEASIBLE:
    print("No feasible schedule can be generated due to impossible constraints.")
    exit()
elif status == cp_model.FEASIBLE or status == cp_model.OPTIMAL:
    initial_schedule = {}
    for section in sections:
        slot = solver.Value(section_slot[section])
        room = rooms[solver.Value(section_room[section])]
        initial_schedule[section] = {'slot': slot, 'room': room}
else:
    print("Solver did not find a solution within the time limit.")
    exit()

# Function to detect clashes
def detect_clashes(schedule):
    room_time_slots = {}
    teacher_time_slots = {}
    student_time_slots = {}

    for section, info in schedule.items():
        slot = info['slot']
        room = info['room']
        teacher = section_teacher[section]
        students_in_section = section_students[section]

        room_key = (slot, room)
        teacher_key = (slot, teacher)

        # Check room clashes
        if room_key in room_time_slots:
            return True  # Clash detected
        else:
            room_time_slots[room_key] = section

        # Check teacher clashes
        if teacher_key in teacher_time_slots:
            return True  # Clash detected
        else:
            teacher_time_slots[teacher_key] = section

        # Check student clashes
        for student in students_in_section:
            student_key = (slot, student)
            if student_key in student_time_slots:
                return True  # Clash detected
            else:
                student_time_slots[student_key] = section

    return False  # No clashes detected

# Detect clashes in the initial schedule
if detect_clashes(initial_schedule):
    print("Clashes detected in the schedule. No valid timetable can be generated with the given constraints.")
    exit()
else:
    # Proceed to output the schedule
    optimized_schedule = initial_schedule

# Mapping slots back to days and times
days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday']
times = ['8:00-10:00', '10:00-12:00', '12:00-14:00', '14:00-16:00', '16:00-18:00']

def slot_to_day_time(slot_number):
    day_index = (slot_number - 1) // 5  # Each day has 5 slots
    time_index = (slot_number - 1) % 5
    if day_index >= len(days) or time_index >= len(times):
        return 'Unknown Day', 'Unknown Time'
    day = days[day_index]
    time = times[time_index]
    return day, time

# Output the optimized schedule
print("\nOptimized Schedule:")
for section, info in optimized_schedule.items():
    slot = info['slot']
    room = info['room']
    course = section_course[section]
    teacher = section_teacher[section]
    day, time = slot_to_day_time(slot)
    print(f"Section {section} ({course}) taught by {teacher} on {day} at {time} in {room}")

# Generate the master timetable and save to CSV
master_filename = os.path.join(save_directory, "Master_Timetable.csv")
with open(master_filename, 'w', newline='') as csvfile:
    fieldnames = ['Section', 'Course', 'Teacher', 'Students', 'Day', 'Time', 'Room']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    for section in sections:
        slot = optimized_schedule[section]['slot']
        room = optimized_schedule[section]['room']
        day, time = slot_to_day_time(slot)
        course = section_course[section]
        teacher = section_teacher[section]
        enrolled_students = section_students[section]
        students_str = ', '.join(enrolled_students)
        writer.writerow({
            'Section': section,
            'Course': course,
            'Teacher': teacher,
            'Students': students_str,
            'Day': day,
            'Time': time,
            'Room': room
        })

print(f"\nMaster timetable saved to {master_filename}")