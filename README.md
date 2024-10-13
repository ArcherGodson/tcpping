# TCP Ping Utility

`tcpping` is a simple command-line utility designed to test the connectivity of a specific host by sending TCP packets. It is a useful tool for diagnosing network issues and verifying the availability of network services.

## Features

- **TCP Based:** Unlike traditional ICMP ping, `tcpping` utilizes TCP to check the status of a host.
- **Customizable Options:** Specify the port, number of attempts, interval between pings, and timeout duration.
- **Infinite Attempts:** Option to keep sending requests until manually stopped.

## Installation

You can download the `tcpping.py` file from the project repository. Ensure you have Python installed on your system.

```bash
git clone https://github.com/ArcherGodson/tcpping
cd tcpping
```

## Usage

```bash
./tcpping.py [-h] [-c COUNT] [-i INTERVAL] [-p PORT] [-t TIMEOUT] host[:port]
```

### Positional Arguments

- `host`  
  Host[:port] to TCP Ping.

### Options

- `-h, --help`  
  Show this help message and exit.
  
- `-c COUNT, --count COUNT`  
  Number of attempts (default: infinite).
  
- `-i INTERVAL, --interval INTERVAL`  
  Interval in seconds between sending each packet (default: 1).
  
- `-p PORT, --port PORT`  
  Port to TCP Ping (default: 80).
  
- `-t TIMEOUT, --timeout TIMEOUT`  
  Timeout in seconds (default: 3).

## Example

```bash
./tcpping.py example.com -c 5 -p 443
```
or
```bash
./tcpping.py example.com:443 -c 5 -i 0.2
```


## Screenshots

be soon

## License

This project is licensed under the MIT License. See the LICENSE file for more details.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue for any suggestions or improvements.

---

Feel free to fill in the placeholders with actual screenshot links when you have them ready.
