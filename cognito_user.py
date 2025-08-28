import boto3
import argparse
import re

class CognitoUserManager:
    def __init__(self):
        self.client = boto3.client('cognito-idp')

    def is_password_strong(self, password):
        """Validate password strength."""
        if len(password) < 8:
            return False, "Password must be at least 8 characters long."
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter."
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter."
        if not re.search(r'\d', password):
            return False, "Password must contain at least one digit."
        if not re.search(r'[\W_]', password):
            return False, "Password must contain at least one special character."
        return True, ""

    #Method to Create User
    def create_user(self, user_pool_id, username, password):
        """Create Cognito user with permanent password."""
        valid, msg = self.is_password_strong(password)
        if not valid:
            print(f"[✗] Password validation failed: {msg}")
            return

        try:
            self.client.admin_create_user(
                UserPoolId=user_pool_id,
                Username=username,
                TemporaryPassword=password,
                MessageAction='SUPPRESS',
                UserAttributes=[
                    {"Name": "email", "Value": username},
                    {"Name": "email_verified", "Value": "true"}
                ]
            )
            self.client.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=username,
                Password=password,
                Permanent=True
            )
            print(f"[✓] User '{username}' created successfully.")
        except self.client.exceptions.UsernameExistsException:
            print(f"[!] User '{username}' already exists.")
        except Exception as e:
            print(f"[✗] Failed to create user: {e}")

    #Method to delete user
    def delete_user(self, user_pool_id, username):
        """Delete a user from the Cognito User Pool."""
        try:
            self.client.admin_delete_user(
                UserPoolId=user_pool_id,
                Username=username
            )
            print(f"[✓] User '{username}' deleted successfully.")
        except self.client.exceptions.UserNotFoundException:
            print(f"[!] User '{username}' not found.")
        except Exception as e:
            print(f"[✗] Failed to delete user: {e}")

    #Method to get token for a user
    def get_tokens(self, user_pool_id, client_id, username, password):
        """Authenticate user and return tokens."""
        try:
            response = self.client.admin_initiate_auth(
                UserPoolId=user_pool_id,
                ClientId=client_id,
                AuthFlow='ADMIN_NO_SRP_AUTH',
                AuthParameters={
                    'USERNAME': username,
                    'PASSWORD': password
                }
            )
            tokens = response['AuthenticationResult']
            print("[✓] Tokens generated successfully:\n")
            print("Access Token:\n", tokens['AccessToken'])
            print("\nID Token:\n", tokens['IdToken'])
        except Exception as e:
            print(f"[✗] Failed to get tokens: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Cognito users and tokens.")
    parser.add_argument('--action', choices=['create', 'token', 'delete'], required=True, help='Action to perform: create, token, or delete')
    parser.add_argument('--username', required=True, help='Username (email recommended)')
    parser.add_argument('--password', required=False, help='Password (required for create and token actions)')
    parser.add_argument('--user-pool-id', required=True, help='Cognito User Pool ID')
    parser.add_argument('--client-id', required=False, help='Cognito App Client ID (required for token action)')

    args = parser.parse_args()

    manager = CognitoUserManager()

    if args.action == 'create':
        if not args.password:
            print("[✗] --password is required for creating a user.")
        else:
            manager.create_user(args.user_pool_id, args.username, args.password)
    elif args.action == 'token':
        if not args.client_id or not args.password:
            print("[✗] --client-id and --password are required for token generation.")
        else:
            manager.get_tokens(args.user_pool_id, args.client_id, args.username, args.password)
    elif args.action == 'delete':
        manager.delete_user(args.user_pool_id, args.username)
