# docker-openairinterface-epc
OAI EPC running in docker-based containers from [OpenAirInterface project](https://gitlab.eurecom.fr/oai/openairinterface5g/wikis/home) develop code base. I am using an Ubuntu 17.04 as host for my tests.

## Configure 

Edit the various Dockerfile or override the corresponding arg variable to match your environement (i.e. UE IMSI, Ki, OPC etc.)

## Build

> docker-compose build --no-cache

## Run 

> docker-compose up 


## Test oaisim
```
source oaienv
~/openairinterface5g/cmake_targets/build_oai -I
~/openairinterface5g/cmake_targets/build_oai -c --UE --oaisim
# ./build_oai -I --UE --oaisim -c -C
sudo -E ~/openairinterface5g/cmake_targets/tools/run_enb_ue_virt_s1 --config-file ~/docker-openairinterface-epc/enb.band7.generic.oaisim.local_mme.conf
ping google.com -I oip1 
```

### Test lte-uesoftmodem (branch develop)
```
# ./build_oai -I -t ETHERNET -w --UE -c -C
```

