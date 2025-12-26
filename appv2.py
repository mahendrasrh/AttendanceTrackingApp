# --- NEW CODE (Local MongoDB) ---
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import urllib.parse
import jwt 
from datetime import datetime, timedelta, timezone
from functools import wraps 
from flask_bcrypt import Bcrypt 
import uuid 


# ... (other imports)

# Remove urllib.parse import if no longer needed for other things

# --- Configuration & Initialization ---

# !!! IMPORTANT: Replace with a strong, secret key for JWT signing
SECRET_KEY = 'your_super_secret_jwt_key_here_please_change' 

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Enable CORS for all origins, allowing the React frontend to communicate
CORS(app)
bcrypt = Bcrypt(app) # Initialize Bcrypt

# ... (Logging Setup remains the same)

# --- MongoDB Connection Configuration (Local Setup) ---

# Set the URI for a local MongoDB instance running on the default port (27017)
# You can add user authentication details here if your local DB requires them.
MONGO_URI = "mongodb://localhost:27017/"
app.logger.info(f"MongoDB connection attempt using local URI: {MONGO_URI}")

# MongoDB connection
client = None
db = None
users_collection = None 
tenants_collection = None 
employees_collection = None # Renamed from students_collection
attendance_collection = None # NEW: For clock-in/out records

try:
    client = MongoClient(MONGO_URI)
    # Use a specific database name for your application
    db = client.get_database("Attendance_System_DB") 
    
    # Initialize Collections
    users_collection = db.users 
    tenants_collection = db.tenants 
    employees_collection = db.employees_info 
    attendance_collection = db.attendance_logs 
    
    client.admin.command('ping') 
    app.logger.info("Successfully connected to local MongoDB!") 
    print("Successfully connected to local MongoDB!")
    
except Exception as e:
    app.logger.error(f"FATAL ERROR: Failed to connect to MongoDB: {e}") 
    
# ... (The rest of your app.py code continues here)


# Upload configuration
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Authentication and Authorization Decorators ---

def token_required(f):
    """Decorator to check for a valid JWT token in the request headers."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

        if not token:
            app.logger.warning("Token missing in request header.")
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.current_user = data
            app.logger.info(f"User {data.get('username')} (Tenant {data.get('tenant_id')}) authenticated.")
        except jwt.ExpiredSignatureError:
            app.logger.warning("Expired token received.")
            return jsonify({'message': 'Token is expired!'}), 401
        except jwt.InvalidTokenError:
            app.logger.error("Invalid token received.")
            return jsonify({'message': 'Token is invalid!'}), 401

        return f(*args, **kwargs)

    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Calls the existing token_required logic to verify the JWT
        result = token_required(f)(*args, **kwargs)
        
        # Check if token_required returned an error response
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
            return result
        
        # Now check for 'admin' role in the roles array
        if 'admin' not in request.current_user.get('roles', []):
            return jsonify({'message': 'Authorization failed: Admin privileges required'}), 403
            
        return f(*args, **kwargs)
    return decorated

def team_required(required_teams):
    """
    Decorator to check if the user belongs to any of the specified teams/roles.
    required_teams must be a list of strings (e.g., ['hr_team', 'finance_team'])
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. First, verify the JWT is valid (re-use token_required logic)
            # This is a common pattern to ensure the token is authenticated before checking specific roles
            result = token_required(f)(*args, **kwargs)
            
            # Check if token_required returned an error response
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
                return result
                
            user_roles = request.current_user.get('roles', [])
            
            # 2. Check for intersection: Does the user have any of the required teams?
            is_authorized = any(team in user_roles for team in required_teams)
            
            # 3. Admins are generally granted access to all team-required routes
            if 'admin' in user_roles:
                is_authorized = True

            if not is_authorized:
                return jsonify({'message': f'Authorization failed: Required teams ({", ".join(required_teams)}) access denied.'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

    
# --- Tenant and User Registration Routes ---

@app.route('/api/register_tenant', methods=['POST'])
def register_tenant():
    """
    Registers a new educational institution (tenant) and creates its initial administrator user.
    """
    if client is None or users_collection is None or tenants_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    
    required_fields = ['institution_name', 'admin_username', 'admin_password']
    if not all(field in data for field in required_fields):
        app.logger.warning(f"Tenant registration failed: Missing fields in request.")
        return jsonify({'message': 'Missing required fields: institution_name, admin_username, admin_password'}), 400

    institution_name = data['institution_name']
    admin_username = data['admin_username']
    admin_password = data['admin_password']

    new_tenant_id = str(uuid.uuid4().hex)[:6].upper()
    
    if tenants_collection.find_one({"name": institution_name}):
        app.logger.warning(f"Tenant registration conflict: Institution name '{institution_name}' already registered.")
        return jsonify({'message': f"Institution name '{institution_name}' is already registered."}), 409

    tenant_data = {
        "tenant_id": new_tenant_id,
        "name": institution_name,
        "date_registered": datetime.now(timezone.utc).isoformat()
    }

    hashed_password = bcrypt.generate_password_hash(admin_password).decode('utf-8')
    admin_user_data = {
        "username": admin_username,
        "password": hashed_password,
        "role": "admin",
        "tenant_id": new_tenant_id 
    }

    try:
        if users_collection.find_one({"username": admin_username}):
            app.logger.warning(f"Admin username conflict during tenant registration: '{admin_username}' globally taken.")
            return jsonify({'message': f"Admin username '{admin_username}' is already taken."}), 409

        tenants_collection.insert_one(tenant_data)
        users_collection.insert_one(admin_user_data)
        app.logger.info(f"New Tenant '{institution_name}' registered with ID: {new_tenant_id}. Admin user '{admin_username}' created.")

        return jsonify({
            "message": f"Institution '{institution_name}' registered successfully.",
            "tenant_id": new_tenant_id,
            "admin_username": admin_username,
            "login_instructions": "Use this tenant_id along with the admin username and password to log in."
        }), 201

    except Exception as e:
        app.logger.error(f"Error during tenant registration for {institution_name}: {e}")
        return jsonify({"error": "Server error during registration. Please try again."}), 500  

# --- Login Route ---

@app.route('/api/login', methods=['POST'])
def login():
    """
    Handles user login. Issues a JWT containing role, tenant_id, AND employee_id.
    """
    if client is None or users_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    auth = request.get_json()

    if not auth or not auth.get('username') or not auth.get('password') or not auth.get('tenant_id'):
        return jsonify({'message': 'Missing username, password, or tenant_id'}), 400

    user = users_collection.find_one({
        'username': auth['username'],
        'tenant_id': auth['tenant_id']
    })

    if not user:
        return jsonify({'message': 'Login failed: Invalid credentials'}), 401
    
    if bcrypt.check_password_hash(user['password'], auth['password']):
        
        payload = {
            'username': user['username'],
            'role': user['role'],
            'tenant_id': user['tenant_id'], 
            'employee_id': user.get('employee_id'), # NEW: Include Employee ID in the token
            'exp': datetime.now(timezone.utc) + timedelta(hours=2),
            'iat': datetime.now(timezone.utc)
        }
        
        token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
        
        app.logger.info(f"User '{user['username']}' successfully logged in.")
        
        return jsonify({
            'username': user['username'],
            'token': token, 
            'role': user['role'], 
            'tenant_id': user['tenant_id'],
            'employee_id': user.get('employee_id') # Return it directly to the client
        }), 200

    return jsonify({'message': 'Login failed: Invalid credentials'}), 401

@app.route('/api/onboard_employee', methods=['POST'])
@team_required(['admin','hr_team'])
def onboard_employee():
    """
    Consolidated API to create both the Employee Profile and the linked User Login Account.
    This replaces separate calls to /api/employees and /api/add_user.
    """
    if client is None or employees_collection is None or users_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    tenant_id = request.current_user.get('tenant_id')

    # --- 1. Validate Required Fields ---
    
    # Fields required for both Employee Profile and User Login
    required_fields = ['employee_id', 'name', 'position', 'business_unit', 'username', 'password']
    if not all(field in data for field in required_fields):
        missing = [f for f in required_fields if f not in data]
        return jsonify({'message': f'Missing required fields: {", ".join(missing)}'}), 400

    employee_id = str(data['employee_id'])
    new_username = data['username']
    new_password = data['password']
    
    # Optional fields
    reports_to_ids = data.get('reports_to_employee_ids', []) 
    if isinstance(reports_to_ids, str): reports_to_ids = [reports_to_ids]
    new_role = data.get('role', 'user').lower()
    
    if new_role not in ['user', 'admin']:
          return jsonify({'message': "Invalid role specified. Must be 'user' or 'admin'."}), 400

    # --- 2. Conflict Checks ---

    # A. Check for employee ID conflict
    if employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id}):
        return jsonify({'message': f"Employee ID '{employee_id}' is already registered."}), 409 
    
    # B. Check for username conflict
    if users_collection.find_one({"username": new_username, "tenant_id": tenant_id}):
        return jsonify({'message': f"Username '{new_username}' is already taken."}), 409 

    # C. Check for manager existence (optional, but good practice)
    if reports_to_ids:
        approver_check = employees_collection.find({"employee_id": {"$in": reports_to_ids}, "tenant_id": tenant_id})
        found_approver_ids = [emp['employee_id'] for emp in approver_check]
        missing_ids = [id for id in reports_to_ids if id not in found_approver_ids]
        if missing_ids:
            return jsonify({'message': f"Manager IDs not found in this institution: {', '.join(missing_ids)}"}), 400

    # --- 3. Data Construction ---

    # Employee Profile Data
    new_employee_data = {
        "employee_id": employee_id,
        "tenant_id": tenant_id,
        "name": data['name'],
        "position": data['position'],
        "business_unit": data['business_unit'],
        "contact_email": data.get('contact_email', new_username), # Use username as fallback email
        "reports_to_employee_ids": reports_to_ids,
        "is_active": data.get('is_active', True),
        "date_added": datetime.now(timezone.utc).isoformat()
    }
    
    # User Login Data
    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    new_user_data = {
        "username": new_username,
        "password": hashed_password,
        "role": new_role,
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "is_active": True # Login is active by default upon creation
    }

    # --- 4. Atomic Database Operation ---
    
    try:
        # Create Employee Profile
        employees_collection.insert_one(new_employee_data)
        
        # Create Linked User Login
        users_collection.insert_one(new_user_data)
        
        app.logger.info(f"Unified onboarding successful for Employee {employee_id} ({new_username}).")
        
        return jsonify({
            "message": f"Employee '{data['name']}' and linked User Login created successfully.",
            "employee_id": employee_id,
            "username": new_username,
            "role": new_role
        }), 201

    except Exception as e:
        # If one insert fails after the first, you might need rollback logic here.
        # For MongoDB, the simplest rollback is to try and clean up what was successfully inserted.
        employees_collection.delete_one({"employee_id": employee_id, "tenant_id": tenant_id})
        users_collection.delete_one({"username": new_username, "tenant_id": tenant_id})
        
        app.logger.error(f"Error during unified onboarding for {employee_id}. Attempted rollback: {e}")
        return jsonify({"error": "Server error during onboarding. Transaction failed and rolled back."}), 500

@app.route('/api/employees', methods=['GET'])
@admin_required
def get_all_employees():
    """
    Retrieves a list of all employees belonging to the admin's tenant.
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    
    try:
        # Find all employees for the current tenant
        employee_list = list(employees_collection.find({"tenant_id": tenant_id}, {'_id': 0}))
        
        # NOTE: Consider pagination for large numbers of employees in a real-world app.
        
        app.logger.info(f"Retrieved {len(employee_list)} employees for tenant {tenant_id}.")
        return jsonify(employee_list), 200
    except Exception as e:
        app.logger.error(f"Error retrieving employees for tenant {tenant_id}: {e}")
        return jsonify({"error": "Server error retrieving employee list."}), 500

@app.route('/api/employee/<employee_id>', methods=['GET'])
@admin_required
def get_single_employee(employee_id):
    """
    Retrieves details for a single employee by their ID within the tenant.
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    
    try:
        employee = employees_collection.find_one({
            "employee_id": employee_id,
            "tenant_id": tenant_id
        }, {'_id': 0})

        if employee:
            app.logger.info(f"Retrieved details for employee ID {employee_id} in tenant {tenant_id}.")
            return jsonify(employee), 200
        else:
            app.logger.warning(f"Employee ID {employee_id} not found in tenant {tenant_id}.")
            return jsonify({"message": f"Employee ID {employee_id} not found in this institution."}), 404
    except Exception as e:
        app.logger.error(f"Error retrieving employee {employee_id} for tenant {tenant_id}: {e}")
        return jsonify({"error": "Server error retrieving employee details."}), 500 


@app.route('/api/employee/<employee_id>', methods=['PUT'])
@admin_required
def update_employee(employee_id):
    """
    Allows an admin to update an employee's details (e.g., position, business_unit, reports_to, or status).
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    update_data = request.get_json()
    
    # 1. Validation for the employee's existence
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        return jsonify({"message": f"Employee ID {employee_id} not found."}), 404
        
    # --- Special Handling for Offboarding ---
    # If the request includes is_active=False, we can trigger offboarding actions
    if 'is_active' in update_data and update_data['is_active'] == False:
        # A. Disable Login Account (Crucial for security)
        users_collection.update_one(
            {"employee_id": employee_id, "tenant_id": tenant_id},
            {"$set": {"is_active": False, "status_note": "Terminated/Inactive"}}
        )
        app.logger.info(f"User login disabled for employee {employee_id} in tenant {tenant_id}.")
        
        # B. Clean up open attendance session
        # Find and clock-out any open session for the employee (prevents phantom work hours)
        attendance_collection.update_one(
            {"employee_id": employee_id, "tenant_id": tenant_id, "clock_out_time": {"$exists": False}},
            {"$set": {"clock_out_time": datetime.now(timezone.utc).isoformat(), "status": "OUT (System Offboard)"}}
        )
        
    # --- General Data Update ---
    
    # Clean up the payload to avoid trying to overwrite immutable fields
    update_data.pop('employee_id', None)
    update_data.pop('tenant_id', None)

    try:
        employees_collection.update_one(
            {"_id": employee['_id']},
            {"$set": update_data}
        )
        app.logger.info(f"Employee {employee_id} updated successfully.")
        return jsonify({"message": f"Employee {employee_id} data and status updated successfully."}), 200

    except Exception as e:
        app.logger.error(f"Error updating employee {employee_id}: {e}")
        return jsonify({"error": "Server error during employee update."}), 500

@app.route('/api/employee/<employee_id>', methods=['DELETE'])
@admin_required
def delete_employee(employee_id):
    """
    Allows an admin to completely delete an employee and all related data (user login, attendance, leave requests).
    This action is irreversible and should be used with caution.
    """
    # if client is None or employees_collection is None or users_collection is None or attendance_collection is None or leave_requests_collection is None:
    #     return jsonify({"error": "Database connection not established."}), 500


    if client is None or employees_collection is None or users_collection is None or attendance_collection is None:
        return jsonify({"error": "Database connection not established."}), 500    

    tenant_id = request.current_user.get('tenant_id')
    
    # 1. Validation for the employee's existence
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        app.logger.warning(f"Deletion failed: Employee ID {employee_id} not found in tenant {tenant_id}.")
        return jsonify({"message": f"Employee ID {employee_id} not found."}), 404

    try:
        # --- CASCADE CLEANUP OPERATIONS ---
        
        # A. Disable/Delete Login Account
        # We will delete the login account linked to this employee_id
        users_result = users_collection.delete_many({"employee_id": employee_id, "tenant_id": tenant_id})
        
        # B. Clean up Attendance Logs (Optional: DELETE vs. Anonymize/Retain)
        # Choosing to delete the logs for a clean removal.
        attendance_result = attendance_collection.delete_many({"employee_id": employee_id, "tenant_id": tenant_id})

        # C. Clean up Leave Requests (as the person making the request)
        # Delete all pending/historical leave requests made by this employee
        leave_req_result = leave_requests_collection.delete_many({"employee_id": employee_id, "tenant_id": tenant_id})

        # D. Clean up Leave Approvals (as a manager)
        # Remove the departing employee from any pending requests where they were an approver.
        # This prevents requests from being stuck if they were the only approver.
        leave_requests_collection.update_many(
            {"tenant_id": tenant_id, "approvals_needed.approver_id": employee_id, "status": "Pending"},
            {
                "$pull": {"approvals_needed": {"approver_id": employee_id}}
            }
        )
        # If any request is now left with zero approvers needed, the admin should manually review/finalize it.
        
        # E. Delete the main Employee Profile
        employee_result = employees_collection.delete_one({"_id": employee['_id']})
        
        # --- Log and Response ---
        
        app.logger.info(f"Employee {employee_id} ({employee['name']}) and associated records fully deleted by admin {request.current_user.get('username')} in tenant {tenant_id}.")
        
        return jsonify({
            "message": f"Employee {employee_id} ({employee['name']}) successfully deleted.",
            "records_deleted": {
                "user_accounts": users_result.deleted_count,
                "employee_profiles": employee_result.deleted_count,
                "attendance_logs": attendance_result.deleted_count,
                "leave_requests_submitted": leave_req_result.deleted_count,
            },
            "next_step_required": "Manually run /api/hierarchy/reassign to update the direct reports of this deleted employee."
        }), 200

    except Exception as e:
        app.logger.error(f"FATAL ERROR during employee deletion for {employee_id}: {e}")
        return jsonify({"error": "Server error during cascade deletion."}), 500        

@app.route('/api/hierarchy/reassign', methods=['POST'])
@admin_required
def reassign_hierarchy():
    """
    Reassigns all employees who reported to an 'old_manager_id' to a 'new_manager_id'.
    """
    if client is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    data = request.get_json()
    tenant_id = request.current_user.get('tenant_id')

    required_fields = ['old_manager_id', 'new_manager_id']
    if not all(field in data for field in required_fields):
        return jsonify({'message': 'Missing required fields: old_manager_id, new_manager_id'}), 400

    old_id = str(data['old_manager_id'])
    new_id = str(data['new_manager_id'])
    
    # 1. Validation: Ensure the new manager exists
    if not employees_collection.find_one({"employee_id": new_id, "tenant_id": tenant_id}):
        return jsonify({"message": f"New Manager ID {new_id} not found."}), 404

    # 2. Query to find all employees reporting to the old manager
    # We use $in to search within the array and $ne to ensure the old manager isn't the new manager
    query = {
        "tenant_id": tenant_id,
        "reports_to_employee_ids": old_id,
        "employee_id": {"$ne": new_id} # Exclude the new manager from reporting to themselves
    }
    
    # 3. Update Operation (Atomic update for all matching documents)
    try:
        # $pull removes the old_manager_id from the array
        employees_collection.update_many(
            query, 
            {"$pull": {"reports_to_employee_ids": old_id}}
        )
        
        # $addToSet adds the new_manager_id, ensuring no duplicates
        result = employees_collection.update_many(
            query,
            {"$addToSet": {"reports_to_employee_ids": new_id}}
        )
        
        count = result.modified_count
        app.logger.info(f"Reassigned {count} employees from {old_id} to {new_id}.")

        return jsonify({
            "message": f"Successfully reassigned hierarchy for {count} employees.",
            "employees_modified": count,
            "old_manager_id": old_id,
            "new_manager_id": new_id
        }), 200

    except Exception as e:
        app.logger.error(f"Error during hierarchy reassignment: {e}")
        return jsonify({"error": "Server error during hierarchy reassignment."}), 500        

# --- Attendance Tracking Routes (Clock In/Out) ---

@app.route('/api/clock_in', methods=['POST'])
@token_required 
def clock_in():
    """
    Records an employee's clock-in time, now including their business unit.
    """
    if client is None or employees_collection is None or attendance_collection is None:
        return jsonify({"error": "Database connection not established."}), 500
    
    data = request.get_json()
    employee_id = data.get('employee_id')
    tenant_id = request.current_user.get('tenant_id')
    
    if not employee_id:
        return jsonify({'message': 'Missing employee_id'}), 400

    # 1. Verify Employee exists and get their business unit
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        app.logger.warning(f"Clock-in failure in tenant {tenant_id}: Employee ID {employee_id} not found.")
        return jsonify({'message': 'Invalid Employee ID for this institution'}), 404
    
    employee_unit = employee.get('business_unit', 'Unassigned') # Fetch the unit

    # 2. Check if the employee is already clocked in
    latest_log = attendance_collection.find_one({
        "employee_id": employee_id, 
        "tenant_id": tenant_id,
        "clock_out_time": {"$exists": False} 
    }, sort=[('clock_in_time', -1)])

    if latest_log:
        app.logger.warning(f"Clock-in failure: Employee {employee_id} is already clocked in.")
        return jsonify({'message': 'Employee is already clocked in.'}), 409

    # 3. Record Clock-In
    now_utc = datetime.now(timezone.utc)
    log_data = {
        "employee_id": employee_id,
        "tenant_id": tenant_id,
        "business_unit": employee_unit, # NEW FIELD added to log
        "clock_in_time": now_utc.isoformat(),
        "status": "IN"
    }
    
    try:
        attendance_collection.insert_one(log_data)
        app.logger.info(f"Employee {employee_id} ({employee_unit}) clocked in at {now_utc.isoformat()}.")
        return jsonify({
            "message": f"{employee['name']} ({employee_unit}) clocked in successfully.",
            "time": now_utc.isoformat(),
            "business_unit": employee_unit,
            "status": "IN"
        }), 201
    except Exception as e:
        app.logger.error(f"Error during clock-in for employee {employee_id}: {e}")
        return jsonify({"error": "Server error during clock-in."}), 500

         
@app.route('/api/clock_out', methods=['POST'])
@token_required 
def clock_out():
    """
    Records an employee's clock-out time, updating the last un-clocked-out record.
    Also calculates the duration of the work session.
    """
    if client is None or employees_collection is None or attendance_collection is None:
        return jsonify({"error": "Database connection not established."}), 500
    
    data = request.get_json()
    employee_id = data.get('employee_id')
    tenant_id = request.current_user.get('tenant_id')

    if not employee_id:
        return jsonify({'message': 'Missing employee_id'}), 400

    # 1. Verify Employee exists within the tenant
    employee = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee:
        app.logger.warning(f"Clock-out failure: Employee ID {employee_id} not found in tenant {tenant_id}.")
        return jsonify({'message': 'Invalid Employee ID for this institution'}), 404

    # 2. Find the latest record that is still "IN" (i.e., missing clock_out_time)
    log_query = {
        "employee_id": employee_id, 
        "tenant_id": tenant_id,
        "clock_out_time": {"$exists": False} # The key condition: only find open sessions
    }
    
    # Sort by clock_in_time descending to get the most recent open session
    latest_in_log = attendance_collection.find_one(log_query, sort=[('clock_in_time', -1)])
    
    if not latest_in_log:
        app.logger.warning(f"Clock-out failure: Employee {employee_id} attempted to clock out but was not clocked in.")
        return jsonify({'message': 'Employee is not currently clocked in. Cannot clock out.'}), 404

    # 3. Record Clock-Out
    now_utc = datetime.now(timezone.utc)
    
    try:
        # Update the found document with the clock-out time and final status
        attendance_collection.update_one(
            {"_id": latest_in_log['_id']},
            {"$set": {
                "clock_out_time": now_utc.isoformat(),
                "status": "OUT"
            }}
        )
        
        # 4. Calculate duration for confirmation
        # Convert the stored ISO string back to a datetime object with UTC timezone awareness
        clock_in_time = datetime.fromisoformat(latest_in_log['clock_in_time'].replace('Z', '+00:00'))
        duration = now_utc - clock_in_time
        
        total_seconds = duration.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        
        app.logger.info(f"Employee {employee_id} clocked out at {now_utc.isoformat()}. Duration: {hours}h {minutes}m.")
        
        return jsonify({
            "message": f"{employee['name']} clocked out successfully.",
            "time": now_utc.isoformat(),
            "duration": f"{hours} hours and {minutes} minutes",
            "status": "OUT",
            "business_unit": latest_in_log.get('business_unit') # Return the unit from the log
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error during clock-out for employee {employee_id}: {e}")
        return jsonify({"error": "Server error during clock-out."}), 500

# Leave application part


@app.route('/api/leave/request', methods=['POST'])
@token_required
def submit_leave_request():
    """
    Allows an employee to submit a leave request, setting up a multi-step approval array.
    """
    if client is None or employees_collection is None or leave_requests_collection is None:
        return jsonify({"error": "Database connection not established."}), 500
        
    data = request.get_json()
    tenant_id = request.current_user.get('tenant_id')
    employee_id = data.get('employee_id') 
    
    if not employee_id:
        return jsonify({'message': 'Missing employee_id in request.'}), 400
        
    employee_info = employees_collection.find_one({"employee_id": employee_id, "tenant_id": tenant_id})
    if not employee_info:
        return jsonify({'message': 'Employee not found in this institution.'}), 404
        
    # Get the list of required approvers
    approver_ids = employee_info.get('reports_to_employee_ids', [])
    if not approver_ids:
        # If no approver is defined, auto-approve for simplicity, or reject
        return jsonify({'message': 'No manager defined for this employee. Request rejected (or auto-approved in some systems).'}), 400

    required_fields = ['leave_type', 'start_date', 'end_date', 'reason']
    if not all(field in data for field in required_fields):
        return jsonify({'message': 'Missing required leave details.'}), 400
        
    try:
        request_id = str(uuid.uuid4())
        
        # Look up approver names (if possible) for the tracking array
        approver_details = employees_collection.find({"employee_id": {"$in": approver_ids}}, {"employee_id": 1, "name": 1})
        approver_map = {det['employee_id']: det['name'] for det in approver_details}

        approvals_needed = []
        for approver_id in approver_ids:
            approvals_needed.append({
                "approver_id": approver_id,
                "status": "Pending",
                "name": approver_map.get(approver_id, "Unknown Manager"),
                "decision_date": None
            })

        request_data = {
            "request_id": request_id,
            "tenant_id": tenant_id,
            "employee_id": employee_id,
            "employee_name": employee_info['name'],
            "leave_type": data['leave_type'],
            "start_date": data['start_date'],
            "end_date": data['end_date'],
            "reason": data['reason'],
            "status": "Pending", # Overall status is Pending until all are approved
            "approvals_needed": approvals_needed, # NEW ARRAY
            "requested_on": datetime.now(timezone.utc).isoformat()
        }
        
        leave_requests_collection.insert_one(request_data)
        app.logger.info(f"Multi-step leave request {request_id} submitted by {employee_id}. Pending {len(approver_ids)} approvals.")
        return jsonify({
            "message": "Leave request submitted successfully for multi-level approval.",
            "request_id": request_id,
            "approvers_needed": approver_ids,
            "status": "Pending"
        }), 201

    except Exception as e:
        app.logger.error(f"Error submitting leave request for {employee_id}: {e}")
        return jsonify({"error": "Server error during leave submission."}), 500

# Replace the previous get_pending_leave_requests route with this updated version
@app.route('/api/leave/pending', methods=['GET'])
@token_required
def get_pending_leave_requests():
    """
    Retrieves all pending leave requests where the current logged-in user is a required approver.
    """
    if client is None or leave_requests_collection is None or employees_collection is None:
        return jsonify({"error": "Database connection not established."}), 500

    tenant_id = request.current_user.get('tenant_id')
    query = {"tenant_id": tenant_id}
    
    if request.current_user.get('role') != 'admin':
        # 1. Find the manager's employee_id (Placeholder link)
        manager_employee_info = employees_collection.find_one({"contact_email": request.current_user.get('username'), "tenant_id": tenant_id})
        if not manager_employee_info:
             return jsonify({'message': 'Only designated managers/admins can view approval requests.'}), 403
            
        manager_employee_id = manager_employee_info['employee_id']
        
        # 2. Query for requests where the manager is an approver AND their specific status is 'Pending'
        query.update({
            "status": "Pending",
            "approvals_needed": {
                "$elemMatch": {
                    "approver_id": manager_employee_id,
                    "status": "Pending"
                }
            }
        })
        app.logger.info(f"Manager {manager_employee_id} viewing their pending requests.")
    else:
        # Admin views all pending requests regardless of who the approver is
        query["status"] = "Pending"
        app.logger.info(f"Admin viewing all pending leave requests for tenant {tenant_id}.")
    
    try:
        pending_requests = list(leave_requests_collection.find(query, {'_id': 0}).sort('requested_on', 1))
        return jsonify(pending_requests), 200
        
    except Exception as e:
        app.logger.error(f"Error retrieving pending leave requests: {e}")
        return jsonify({"error": "Server error retrieving leave requests."}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


