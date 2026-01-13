1) Install Venv python -m venv venv
2)Activate Venv \venv\Scripts>activate
3) Install Required Packeges pip install -r requirements.txt (To generate requirements.txt file from venv: pip freeze > requirements.txt)
4)


To Install MonogoDB

https://www.mongodb.com/try/download/community


Tejasvikushwah@gmail.com

Bharath Sugumaran


9.5x4.5

1160 banner + Editing 
150 Sunboard

3*6
4*8

54.5
86


15 wall calendar - 263 * 15 = 3945
10 desk calendar - 242 * 10 = 2420
Small post card - 10 x 4 x 15 qty = 600
Medium post card - 15 x 15 qty = 225
1 sheet Sticker + shape cut-80*1 = 80
Total - 7270


8197736729
office number 



front Address
back website


SCL


zebra
6742


Hi sir one A4 size perfect binding  finishing 





VADA PAV (1 PCS)
ALOO BONDA (2 PCS)
DABELI (1 PCS)
PAV BHAJI (2 BUTTER PAVS)
EXTRA BUTTER PAV
CHEESE & FRIED BITES
₹50
₹70
.₹70
₹100
20

18 

500 qty 700pages


Harish Gowda Sir
RRB Wrestling Private Limited
7349616143



Since we have the backend logic ready for Leave, Attendance, and Tracking, would you like me to:

Help you design the Database Indexes in MongoDB to make sure these tracking and attendance queries stay fast as your data grows?

Or would you like to move on to the Monthly Payroll/Salary Calculation logic based on these attendance hours?




Nithin User

-----------------Admin Reg--------------------

Payload:
{
  "institution_name": "AimorenDigitalSolutions",
  "admin_username": "admin",
  "admin_password": "admin@123"
}

Response :

{
    "admin_username": "admin",
    "login_instructions": "Use this tenant_id along with the admin username and password to log in.",
    "message": "Institution 'AimorenDigitalSolutions' registered successfully.",
    "tenant_id": "0E8707"
}

-----------------Admin Login--------------------
Payload
{
  "username": "admin",
  "password": "admin@123",
  "tenant_id": "0E8707" 
}

response:
{
    "employee_id": "A01",
    "role": "admin",
    "tenant_id": "0E8707",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6ImFkbWluIiwicm9sZSI6ImFkbWluIiwidGVuYW50X2lkIjoiMEU4NzA3IiwiZW1wbG95ZWVfaWQiOiJBMDEiLCJleHAiOjE3Njc4MDk5MzYsImlhdCI6MTc2NzgwMjczNn0.7rGuZby-vFOKWH-jBOUevB8XT8CBjpDNKvyCO1IzCeM",
    "username": "admin"
}
--------------On Board User-------------------------------
Payload
{
    "employee_id": "E1001",
    "name": "Nithin1",
    "position": "Senior Analyst",
    "business_unit": "Strategy & Planning",
    "username": "nithin",
    "password": "nithin@123",
    "role": "user",
    "reports_to_employee_ids": [],
    "contact_email": "nithin@xyz.com"
}

response:
{
    "employee_id": "E1001",
    "message": "Employee 'Nithin1' and linked User Login created successfully.",
    "role": "user",
    "tenant_id": "207D7D",
    "username": "nithin"
}

--------------------User Login---------------------

-----------------Admin Login--------------------