import itertools
import string
import time

def simulate_brute_force(target_length):
    # Define the character set requested (lowercase + uppercase + digits)
    character_pool = string.ascii_lowercase + string.ascii_uppercase + string.digits
    
    print(f"Pool size: {len(character_pool)} characters.")
    print(f"Generating all combinations of length {target_length}...")
    
    start_time = time.time()
    count = 0
    
    # Generate combinations of the specific length
    for combination in itertools.product(character_pool, repeat=target_length):
        # Convert tuple of characters to a single string
        password_guess = "".join(combination)
        count += 1
        
        # Educational placeholder: In a live scenario, this guess would be 
        # passed to a decryption handler to check if it unlocks the file.
        
        # Limit output for demonstration purposes
        if count <= 5:
            print(f"Attempt {count}: {password_guess}")
            
    end_time = time.time()
    print(f"Total combinations checked: {count}")
    print(f"Time elapsed: {end_time - start_time:.4f} seconds")

# Simulate checking a 3-character space
simulate_brute_force(3)