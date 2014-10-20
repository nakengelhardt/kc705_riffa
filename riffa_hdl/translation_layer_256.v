`timescale 1ns/1ns
//----------------------------------------------------------------------------
// This software is Copyright © 2012 The Regents of the University of 
// California. All Rights Reserved.
//
// Permission to copy, modify, and distribute this software and its 
// documentation for educational, research and non-profit purposes, without 
// fee, and without a written agreement is hereby granted, provided that the 
// above copyright notice, this paragraph and the following three paragraphs 
// appear in all copies.
//
// Permission to make commercial use of this software may be obtained by 
// contacting:
// Technology Transfer Office
// 9500 Gilman Drive, Mail Code 0910
// University of California
// La Jolla, CA 92093-0910
// (858) 534-5815
// invent@ucsd.edu
// 
// This software program and documentation are copyrighted by The Regents of 
// the University of California. The software program and documentation are 
// supplied "as is", without any accompanying services from The Regents. The 
// Regents does not warrant that the operation of the program will be 
// uninterrupted or error-free. The end-user understands that the program was 
// developed for research purposes and is advised not to rely exclusively on 
// the program for any reason.
// 
// IN NO EVENT SHALL THE UNIVERSITY OF CALIFORNIA BE LIABLE TO
// ANY PARTY FOR DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR
// CONSEQUENTIAL DAMAGES, INCLUDING LOST PROFITS, ARISING
// OUT OF THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION,
// EVEN IF THE UNIVERSITY OF CALIFORNIA HAS BEEN ADVISED OF
// THE POSSIBILITY OF SUCH DAMAGE. THE UNIVERSITY OF
// CALIFORNIA SPECIFICALLY DISCLAIMS ANY WARRANTIES,
// INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
// MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.
// THE SOFTWARE PROVIDED HEREUNDER IS ON AN "AS IS" BASIS, 
// AND THE UNIVERSITY OF CALIFORNIA HAS NO OBLIGATIONS TO
// PROVIDE MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR
// MODIFICATIONS.
//----------------------------------------------------------------------------
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    19:27:32 05/15/2014 
// Design Name: 
// Module Name:    translation_layer_256
// Project Name: 
// Target Devices: 
// Tool versions: 
// Description:
// Translates Avalon (Altera) signals into Unified (architecture
// independent) streaming signals for riffa. The altera RX interface has a 1 cycle
// latency because it needs to produce several metadata signals that are not 
// provided by the altera PCIe Core.
//
// Dependencies: None
//
// Revision: 
// Revision 0.01 - File Created
// Additional Comments: 
//
//////////////////////////////////////////////////////////////////////////////////
module translation_layer_256
  #(parameter C_ALTERA = 1'b1,
    parameter C_PCI_DATA_WIDTH = 9'd256)
   (	
        input                              CLK,
	    input                              RST_IN,

        // Xilinx Signals
	    input [C_PCI_DATA_WIDTH-1:0]       M_AXIS_RX_TDATA,
	    input [(C_PCI_DATA_WIDTH/8)-1:0]   M_AXIS_RX_TKEEP,
	    input                              M_AXIS_RX_TLAST, // Not used in the 128 bit interface
	    input                              M_AXIS_RX_TVALID,
	    output                             M_AXIS_RX_TREADY,
	    input [(C_PCI_DATA_WIDTH/32):0]    IS_SOF,
	    input [(C_PCI_DATA_WIDTH/32):0]    IS_EOF,
	    input                              RERR_FWD,
   
	    output [C_PCI_DATA_WIDTH-1:0]      S_AXIS_TX_TDATA,
	    output [(C_PCI_DATA_WIDTH/8)-1:0]  S_AXIS_TX_TKEEP,
	    output                             S_AXIS_TX_TLAST,
	    output                             S_AXIS_TX_TVALID,
	    output                             S_AXIS_SRC_DSC,
	    input                              S_AXIS_TX_TREADY,
   
	    input [15:0]                       COMPLETER_ID,
	    input                              CFG_BUS_MSTR_ENABLE, 
	    input [5:0]                        CFG_LINK_WIDTH, // cfg_lstatus[9:4] (from Link Status Register): 000001=x1, 000010=x2, 000100=x4, 001000=x8, 001100=x12, 010000=x16, 100000=x32, others=? 
	    input [1:0]                        CFG_LINK_RATE, // cfg_lstatus[1:0] (from Link Status Register): 01=2.5GT/s, 10=5.0GT/s, others=?
	    input [2:0]                        CFG_MAX_READ_REQUEST_SIZE, // cfg_dcommand[14:12] (from Device Control Register): 000=128B, 001=256B, 010=512B, 011=1024B, 100=2048B, 101=4096B
	    input [2:0]                        CFG_MAX_PAYLOAD_SIZE, // cfg_dcommand[7:5] (from Device Control Register): 000=128B, 001=256B, 010=512B, 011=1024B

	    input                              CFG_INTERRUPT_MSIEN, // 1 if MSI interrupts are enable, 0 if only legacy are supported
	    input                              CFG_INTERRUPT_RDY, // High when interrupt is able to be sent
	    output                             CFG_INTERRUPT, // High to request interrupt, when both CFG_INTERRUPT_RDY and CFG_INTERRUPT are high, interrupt is sent)

        // Altera Signals
        input [C_PCI_DATA_WIDTH-1:0]       RX_ST_DATA,
        input [0:0]                        RX_ST_EOP,
        input [0:0]                        RX_ST_VALID,
        output                             RX_ST_READY,
        input [0:0]                        RX_ST_SOP,
        input [0:0]                        RX_ST_EMPTY,

        output [C_PCI_DATA_WIDTH-1:0]      TX_ST_DATA,
        output [0:0]                       TX_ST_VALID,
        input                              TX_ST_READY,
        output [0:0]                       TX_ST_EOP,
        output [0:0]                       TX_ST_SOP,
		output [0:0]                       TX_ST_EMPTY,

        input [31:0]                       TL_CFG_CTL,
        input [3:0]                        TL_CFG_ADD,
        input [52:0]                       TL_CFG_STS,

        input                              APP_MSI_ACK,
        output                             APP_MSI_REQ,

        // Unified Signals
	    output [C_PCI_DATA_WIDTH-1:0]      RX_DATA,
	    output                             RX_DATA_VALID,
        input                              RX_DATA_READY,

	    output                             RX_TLP_END_FLAG,
	    output [3:0]                       RX_TLP_END_OFFSET,
        output                             RX_TLP_START_FLAG,
	    output [3:0]                       RX_TLP_START_OFFSET,
	    output                             RX_TLP_ERROR_POISON,
   
	    input [C_PCI_DATA_WIDTH-1:0]       TX_DATA,
	    input [(C_PCI_DATA_WIDTH/8)-1:0]   TX_DATA_BYTE_ENABLE,
        input [(C_PCI_DATA_WIDTH/32)-1:0]  TX_DATA_WORD_ENABLE,
	    input                              TX_TLP_END_FLAG,
        input                              TX_TLP_START_FLAG,
	    input                              TX_DATA_VALID,
	    input                              TX_TLP_ERROR_POISON, 
	    output                             TX_DATA_READY,

	    output [15:0]                      CONFIG_COMPLETER_ID,
	    output                             CONFIG_BUS_MASTER_ENABLE, 
	    output [5:0]                       CONFIG_LINK_WIDTH, // cfg_lstatus[9:4] (from Link Status Register): 000001=x1, 000010=x2, 000100=x4, 001000=x8, 001100=x12, 010000=x16, 100000=x32, others=? 
	    output [1:0]                       CONFIG_LINK_RATE, // cfg_lstatus[1:0] (from Link Status Register): 01=2.5GT/s, 10=5.0GT/s, others=?
	    output [2:0]                       CONFIG_MAX_READ_REQUEST_SIZE, // cfg_dcommand[14:12] (from Device Control Register): 000=128B, 001=256B, 010=512B, 011=1024B, 100=2048B, 101=4096B
	    output [2:0]                       CONFIG_MAX_PAYLOAD_SIZE, // cfg_dcommand[7:5] (from Device Control Register): 000=128B, 001=256B, 010=512B, 011=1024B
        output                             CONFIG_INTERRUPT_MSIENABLE, // 1 if MSI interrupts are enable, 0 if only legacy are supported
	    output                             INTR_MSI_RDY, // High when interrupt is able to be sent
	    input                              INTR_MSI_REQUEST // High to request interrupt, when both CFG_INTERRUPT_RDY and CFG_INTERRUPT are high
        );

endmodule
