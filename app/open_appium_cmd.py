import subprocess

def run_multiple_appium_servers(count, starting_port=4723):
    try:
        for i in range(count):
            port = starting_port + i
            command = f'appium --base-path /wd/hub --port {port}'
            subprocess.Popen(
                ['cmd', '/k', command],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            print(f"Started Appium server on port {port}")
    except Exception as e:
        print(f"Error while starting Appium servers: {e}")


run_multiple_appium_servers(1) 
