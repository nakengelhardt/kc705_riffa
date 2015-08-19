A module for FPGA-initiated non-coherent access to host process data using host virtual memory addresses. Data is cached by page and written back on a LRU basis. Uses riffa ( https://github.com/drichmond/riffa/ ) for data transport over PCIe.

Host side support for the example applications is in a separate repository ( https://github.com/nakengelhardt/riffa_c_linux_x64 ).